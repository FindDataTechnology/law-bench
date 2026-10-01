#!/usr/bin/env python3
"""QLoRA SFT trainer for the Judge-C and Drafter-A legs (M2).

Consumes the ChatML files written by ``export_sft_dataset.py`` and finetunes
Qwen3.8-27B with 4bit NF4 + LoRA, reusing the loader that M0's smoke proved
works on this arch (``Qwen3_5ForConditionalGeneration``, transformers 5.x).

Two legs, TWO SEPARATE RUNS — never one joint run
------------------------------------------------
``inspect_sft_lengths.py`` measured (exact, Qwen3 tokenizer)::

    judge_c   (1074)  total p99 2784, max 2946   -> needs 4096
    drafter_a ( 131)  total p99 2660, max 4004   -> needs 4096

Both legs now need 4096 — judge_c's prompt carries the full judged contract
(p50 ~2550 chars) since regrounding, so the pre-regrounding 512 budget would
strip the assistant span from 1063/1074 records (99.0%). The legs stay separate
because they train two different adapters (judge and drafter are distinct
models in the flywheel), not because their sequence budgets differ.

Loss is computed on the ASSISTANT SPAN ONLY
-------------------------------------------
The prompt is masked to -100. Training on the prompt would mean nearly all of
the gradient comes from reproducing the contract and rubric text (judge_c
assistant is ~75 of ~1697 tokens), i.e. memorizing inputs rather than learning
to judge.

Subcommands::

    train_sft.py verify [--leg judge_c|drafter_a|all]   # GPU-free data check
    train_sft.py train  --leg judge_c|drafter_a
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from common import FINETUNE_ROOT, read_jsonl  # noqa: E402

SFT_DIR = FINETUNE_ROOT / "sft"
DEFAULT_MODEL_ID = "Qwen/Qwen3.8-27B"

# Per-leg sequence budget — taken from data/finetune/sft/lengths.json, not guessed.
# Re-run inspect_sft_lengths.py if the data or the base model changes.
LEGS: dict[str, dict] = {
    "judge_c": {
        "max_seq_len": 4096,
        "measured_p99": 2784,
        "measured_max": 2946,
        # The prompt now carries the whole judged contract, so the sequence
        # budget matches the drafter leg — batch accordingly.
        "per_device_batch": 1,
        "grad_accum": 16,
        "epochs": 3.0,
    },
    "drafter_a": {
        "max_seq_len": 4096,
        "measured_p99": 2660,
        "measured_max": 4004,
        # 131 records at 8x the sequence length: keep the micro-batch at 1 and
        # buy the effective batch back with accumulation.
        "per_device_batch": 1,
        "grad_accum": 16,
        "epochs": 4.0,
    },
}

IM_END = "<|im_end|>"


# ----------------------------------------------------------------------------
# example construction — the part that decides whether training works at all
# ----------------------------------------------------------------------------

def build_example(
    tok,
    messages: list[dict],
    max_seq_len: int,
    keep_think: bool = False,
) -> dict:
    """Render one ChatML record into ``input_ids`` / ``labels``.

    The prompt is rendered with ``add_generation_prompt=True`` and the assistant
    content is appended by hand rather than letting ``apply_chat_template``
    render the whole conversation. Two reasons:

    1. Qwen3's template unconditionally injects an empty ``<think>\\n\\n</think>``
       block before assistant content (``enable_thinking=False`` does NOT
       suppress it on this template version). Rendering the target ourselves is
       the only way to keep it out, and for a JSON-emitting judge those 4 tokens
       are pure waste that also teach the model to emit empty think blocks.
    2. Tokenizing prompt and completion separately puts the mask boundary on a
       real token boundary, and matches inference exactly — at inference the
       prompt is tokenized alone and the model generates from there. Tokenizing
       the joined string could merge across the boundary and shift the mask.

    Returns a dict with ``input_ids``, ``labels``, ``n_prompt``, ``n_completion``
    and a ``status`` of ok / overflow / zero_signal.
    """
    if not messages or messages[-1].get("role") != "assistant":
        raise ValueError("last message must be the assistant target")

    prompt_text = tok.apply_chat_template(
        messages[:-1], tokenize=False, add_generation_prompt=True
    )
    target = (messages[-1].get("content") or "")
    if keep_think:
        target = f"<think>\n\n</think>\n\n{target}"

    prompt_ids = tok(prompt_text, add_special_tokens=False)["input_ids"]
    completion_ids = tok(target, add_special_tokens=False)["input_ids"]
    completion_ids = completion_ids + tok(IM_END, add_special_tokens=False)["input_ids"]

    n_prompt, n_completion = len(prompt_ids), len(completion_ids)
    total = n_prompt + n_completion

    # A prompt that alone fills the window leaves no room for a single label
    # token: the record would consume a full forward/backward and backprop
    # nothing. That is never worth keeping, regardless of the overflow policy.
    if n_prompt >= max_seq_len:
        status = "zero_signal"
    elif total > max_seq_len:
        status = "overflow"
    else:
        status = "ok"

    input_ids = prompt_ids + completion_ids
    labels = [-100] * n_prompt + completion_ids
    return {
        "input_ids": input_ids,
        "labels": labels,
        "n_prompt": n_prompt,
        "n_completion": n_completion,
        "total": total,
        "status": status,
    }


def load_leg(
    tok,
    leg: str,
    split: str,
    max_seq_len: int,
    keep_think: bool,
    on_overflow: str,
    sft_dir: pathlib.Path,
) -> tuple[list[dict], dict, list[int]]:
    """Build every example for one leg/split, applying the overflow policy.

    Returns ``(examples, stats, kept_row_indices)``. The third element is what
    lets a caller line an example back up with its source row — examples get
    dropped, so ``zip(rows, examples)`` would silently misalign.
    """
    path = sft_dir / f"{leg}_{split}.jsonl"
    rows = read_jsonl(path)
    if not rows:
        raise SystemExit(f"no records at {path} — run export_sft_dataset.py all first")

    kept: list[dict] = []
    kept_idx: list[int] = []
    stats = {"read": len(rows), "ok": 0, "overflow": 0, "zero_signal": 0, "dropped": 0}
    for i, r in enumerate(rows):
        ex = build_example(tok, r["messages"], max_seq_len, keep_think)
        stats[ex["status"]] += 1
        if ex["status"] == "zero_signal":
            stats["dropped"] += 1
            continue
        if ex["status"] == "overflow":
            if on_overflow == "error":
                raise SystemExit(
                    f"{path.name}: record exceeds max_seq_len ({ex['total']} > {max_seq_len}). "
                    f"Re-check lengths.json — this leg's budget is wrong."
                )
            if on_overflow == "drop":
                stats["dropped"] += 1
                continue
            # truncate: keep the head. Loses the tail of the assistant span,
            # which teaches the model to stop early — hence not the default.
            ex["input_ids"] = ex["input_ids"][:max_seq_len]
            ex["labels"] = ex["labels"][:max_seq_len]
        kept.append({"input_ids": ex["input_ids"], "labels": ex["labels"]})
        kept_idx.append(i)
    stats["kept"] = len(kept)
    return kept, stats, kept_idx


class PadCollator:
    """Pad to the longest sequence IN THE BATCH, not to max_seq_len.

    At 4096 with a p50 of 1912 tokens, padding every batch to the ceiling would
    roughly double the compute for nothing.
    """

    def __init__(self, pad_token_id: int):
        self.pad_token_id = pad_token_id

    def __call__(self, features: list[dict]):
        import torch

        width = max(len(f["input_ids"]) for f in features)
        input_ids, labels, attn = [], [], []
        for f in features:
            n = len(f["input_ids"])
            pad = width - n
            input_ids.append(f["input_ids"] + [self.pad_token_id] * pad)
            labels.append(f["labels"] + [-100] * pad)
            attn.append([1] * n + [0] * pad)
        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
            "attention_mask": torch.tensor(attn, dtype=torch.long),
        }


# ----------------------------------------------------------------------------
# verify — full data-path validation with no GPU and no model weights
# ----------------------------------------------------------------------------

def _verify_leg(tok, leg: str, cfg: dict, args) -> dict:
    max_seq_len = args.max_seq_len or cfg["max_seq_len"]
    out: dict = {"leg": leg, "max_seq_len": max_seq_len, "splits": {}}
    for split in ("train", "val"):
        examples, stats, kept_idx = load_leg(
            tok, leg, split, max_seq_len, args.keep_think, args.on_overflow, args.sft_dir
        )
        rows = read_jsonl(args.sft_dir / f"{leg}_{split}.jsonl")

        # The mask is the whole ballgame: assert the unmasked span decodes back
        # to exactly the assistant content we intended to train on.
        checked = mismatch = shape_bad = 0
        first_bad = None
        for ridx, ex in zip(kept_idx, examples):
            row = rows[ridx]
            labels = ex["labels"]

            # Structural: labels must be a clean run of -100 followed by a run
            # with no -100 in it. A stray -100 inside the completion would mean
            # the boundary arithmetic drifted.
            n_masked = 0
            while n_masked < len(labels) and labels[n_masked] == -100:
                n_masked += 1
            tail = labels[n_masked:]
            if not tail or any(t == -100 for t in tail):
                shape_bad += 1
                if first_bad is None:
                    first_bad = f"row {ridx}: mask is not a clean prefix (masked={n_masked})"
                continue
            if len(labels) != len(ex["input_ids"]) or tail != ex["input_ids"][n_masked:]:
                shape_bad += 1
                if first_bad is None:
                    first_bad = f"row {ridx}: labels tail != input_ids tail"
                continue

            got = tok.decode(tail)
            want = (row["messages"][-1]["content"] or "") + IM_END
            if args.keep_think:
                want = f"<think>\n\n</think>\n\n{want}"
            checked += 1
            if got != want:
                mismatch += 1
                if first_bad is None:
                    first_bad = f"row {ridx}: got={got[:100]!r} want={want[:100]!r}"

        out["splits"][split] = {
            **stats,
            "mask_checked": checked,
            "mask_mismatch": mismatch,
            "mask_shape_bad": shape_bad,
            "first_bad": first_bad,
        }
    return out


def cmd_verify(args: argparse.Namespace) -> int:
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(args.tokenizer, trust_remote_code=True)
    print(f"tokenizer: {args.tokenizer} (vocab={len(tok)})")
    print(f"think block: {'KEPT' if args.keep_think else 'stripped'}   "
          f"overflow policy: {args.on_overflow}\n")

    legs = list(LEGS) if args.leg == "all" else [args.leg]
    reports = [_verify_leg(tok, leg, LEGS[leg], args) for leg in legs]

    bad = 0
    for rep in reports:
        print(f"=== {rep['leg']}  (max_seq_len={rep['max_seq_len']}) ===")
        for split, s in rep["splits"].items():
            drop_pct = 100.0 * s["dropped"] / s["read"] if s["read"] else 0.0
            print(f"  {split:<6} read={s['read']:<5} kept={s['kept']:<5} "
                  f"ok={s['ok']:<5} overflow={s['overflow']:<4} "
                  f"zero_signal={s['zero_signal']:<4} dropped={s['dropped']} ({drop_pct:.1f}%)")
            print(f"         mask: checked={s['mask_checked']} "
                  f"mismatch={s['mask_mismatch']} shape_bad={s['mask_shape_bad']}")
            if s["mask_mismatch"] or s["mask_shape_bad"]:
                bad += 1
                print(f"         FAIL: {s['first_bad']}")
            # An empty split passes every mask check trivially. Without this the
            # 512-on-drafter misconfiguration reports "VERIFY PASSED" while
            # dropping all 131 records.
            if s["kept"] == 0:
                bad += 1
                print(f"         FAIL: every record dropped — max_seq_len "
                      f"{rep['max_seq_len']} is too small for this leg")
            elif drop_pct > 5.0:
                print(f"         WARN: {drop_pct:.1f}% of records dropped")
        print()

    if bad:
        print(f"VERIFY FAILED ({bad} problem(s))")
        return 1
    print("VERIFY PASSED — loss mask exact, no dropped records")
    return 0


# ----------------------------------------------------------------------------
# train
# ----------------------------------------------------------------------------

def _resolve_model(args) -> str:
    """Local path if given, else ModelScope snapshot (china-reachable, no xet)."""
    if args.model_path:
        return args.model_path
    from modelscope import snapshot_download

    allow = ["*.json", "*.txt", "tokenizer*", "*.safetensors", "*.model",
             "*.py", "merges*", "vocab*", "special_tokens_map*", "generation*"]
    ignore = ["*.bin", "*.pt", "*.gguf", "*.onnx", "*.ot", "original/*",
              "consolidated.*", "*.h5", "*.msgpack"]
    print(f"[dl] ModelScope snapshot_download {args.model_id} -> {args.cache_dir}")
    return snapshot_download(
        args.model_id, cache_dir=args.cache_dir,
        allow_patterns=allow, ignore_patterns=ignore, max_workers=1,
    )


def _load_base(model_path: str, base_dtype: str):
    """Load the frozen backbone. 4bit keeps the M0-proven QLoRA path; bf16
    needs ~54GB weights (86GB card: fits, and skips quantization entirely)."""
    import torch
    import transformers
    from transformers import BitsAndBytesConfig

    load_kwargs: dict = {"torch_dtype": torch.bfloat16}
    if base_dtype == "4bit":
        load_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )

    errs = []
    for cls_name in ("AutoModelForCausalLM", "AutoModelForImageTextToText",
                     "Qwen3_5ForConditionalGeneration"):
        cls = getattr(transformers, cls_name, None)
        if cls is None:
            continue
        try:
            print(f"[load] trying {cls_name} (base_dtype={base_dtype}) ...")
            model = cls.from_pretrained(
                model_path, device_map="auto",
                trust_remote_code=True, **load_kwargs,
            )
            model.config.use_cache = False
            print(f"[load] OK via {cls_name}")
            return model
        except Exception as e:  # noqa: BLE001 — try the next auto-class
            errs.append(f"{cls_name}: {type(e).__name__}: {str(e)[:200]}")
            print(f"[load] {cls_name} failed: {type(e).__name__}: {str(e)[:160]}")
    raise SystemExit("all loaders failed:\n  " + "\n  ".join(errs))


def cmd_train(args: argparse.Namespace) -> int:
    import torch
    from transformers import AutoTokenizer, Trainer, TrainingArguments

    cfg = LEGS[args.leg]
    max_seq_len = args.max_seq_len or cfg["max_seq_len"]
    print(f"=== leg={args.leg} max_seq_len={max_seq_len} "
          f"(measured p99={cfg['measured_p99']} max={cfg['measured_max']}) ===")
    if max_seq_len < cfg["measured_max"]:
        print(f"WARNING: max_seq_len {max_seq_len} < measured max {cfg['measured_max']}; "
              f"records will be dropped or truncated.")

    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    model_path = _resolve_model(args)
    tok = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id

    train_ds, tr_stats, _ = load_leg(tok, args.leg, "train", max_seq_len,
                                     args.keep_think, args.on_overflow, args.sft_dir)
    val_ds, va_stats, _ = load_leg(tok, args.leg, "val", max_seq_len,
                                   args.keep_think, args.on_overflow, args.sft_dir)
    print(f"[data] train {tr_stats}\n[data] val   {va_stats}")

    model = _load_base(model_path, args.base_dtype)

    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

    # M0's smoke used r=8 on q+v only, which was enough to prove a grad path
    # exists. A real run needs every projection or the adapter underfits.
    if args.base_dtype == "4bit":
        model = prepare_model_for_kbit_training(
            model, use_gradient_checkpointing=args.grad_checkpointing
        )
    elif args.grad_checkpointing:
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()
    lora = LoraConfig(
        r=args.lora_r, lora_alpha=args.lora_r * 2, lora_dropout=0.05,
        bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    out_dir = pathlib.Path(args.out_dir) / args.leg
    # transformers 5.x dropped warmup_ratio; keep the same 3% intent in steps.
    steps_per_epoch = max(1, len(train_ds) // (args.batch_size or cfg["per_device_batch"]
                                               * (args.grad_accum or cfg["grad_accum"])))
    warmup_steps = max(1, int(steps_per_epoch * cfg["epochs"] * 0.03))
    targs = TrainingArguments(
        output_dir=str(out_dir),
        per_device_train_batch_size=args.batch_size or cfg["per_device_batch"],
        per_device_eval_batch_size=args.batch_size or cfg["per_device_batch"],
        gradient_accumulation_steps=args.grad_accum or cfg["grad_accum"],
        num_train_epochs=args.epochs or cfg["epochs"],
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_steps=warmup_steps,
        logging_steps=5,
        logging_first_step=True,
        # log dicts are printed to stdout; when stdout is a redirected file Python
        # block-buffers them and they never appear until flush. Force line mode.
        disable_tqdm=False,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=2,
        bf16=True,
        gradient_checkpointing=args.grad_checkpointing,
        optim="paged_adamw_8bit",
        report_to=[],
        seed=42,
    )
    trainer = Trainer(
        model=model, args=targs,
        train_dataset=train_ds, eval_dataset=val_ds,
        data_collator=PadCollator(pad_id),
    )

    t0 = time.time()
    trainer.train()
    print(f"[train] done in {time.time() - t0:.0f}s")
    adapter_dir = out_dir / "adapter"
    model.save_pretrained(str(adapter_dir))
    tok.save_pretrained(str(adapter_dir))
    (out_dir / "run_meta.json").write_text(
        json.dumps({
            "leg": args.leg,
            "max_seq_len": max_seq_len,
            "base_dtype": args.base_dtype,
            "keep_think": args.keep_think,
            "on_overflow": args.on_overflow,
            "lora_r": args.lora_r,
            "train_stats": tr_stats,
            "val_stats": va_stats,
            "model_path": model_path,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[save] adapter -> {adapter_dir}")
    if torch.cuda.is_available():
        print(f"[vram] peak_alloc={torch.cuda.max_memory_allocated() / 1e9:.1f}GB")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--sft-dir", type=pathlib.Path, default=SFT_DIR)
    common.add_argument("--max-seq-len", type=int,
                        help="override the per-leg measured budget (not recommended)")
    common.add_argument("--keep-think", action="store_true",
                        help="keep Qwen3's empty <think></think> block in the target")
    common.add_argument("--on-overflow", choices=["drop", "truncate", "error"],
                        default="drop")

    v = sub.add_parser("verify", parents=[common],
                       help="GPU-free: build all examples and assert the loss mask")
    v.add_argument("--leg", choices=[*LEGS, "all"], default="all")
    v.add_argument("--tokenizer", default="Qwen/Qwen3-8B",
                   help="tokenizer repo/path (Qwen3 family shares the template)")
    v.set_defaults(func=cmd_verify)

    t = sub.add_parser("train", parents=[common], help="run QLoRA SFT for one leg")
    t.add_argument("--leg", choices=list(LEGS), required=True)
    t.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    t.add_argument("--model-path", help="skip download, use this local snapshot")
    t.add_argument("--cache-dir", default="/dev/shm/ms_cache")
    t.add_argument("--out-dir", default="/root/autodl-tmp/sft_out")
    t.add_argument("--base-dtype", choices=["4bit", "bf16"], default="4bit",
                   help="frozen backbone storage; bf16 needs ~54GB weights "
                        "(86GB card) but skips quantization")
    t.add_argument("--lora-r", type=int, default=16)
    t.add_argument("--lr", type=float, default=1e-4)
    t.add_argument("--epochs", type=float)
    t.add_argument("--batch-size", type=int)
    t.add_argument("--grad-accum", type=int)
    t.add_argument("--grad-checkpointing", action="store_true", default=True)
    t.add_argument("--no-grad-checkpointing", dest="grad_checkpointing",
                   action="store_false")
    t.set_defaults(func=cmd_train)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
