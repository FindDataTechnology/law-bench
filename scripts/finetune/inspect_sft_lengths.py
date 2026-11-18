#!/usr/bin/env python3
"""Measure token-length distribution of the SFT files to pick M2 ``max_seq_len``.

M0's smoke test ran at ``seq=512`` (26.6GB peak, 4bit QLoRA on A800). That was a
VRAM probe, not a statement about the data. This script answers the question the
smoke could not: **at what sequence length does the training data actually fit?**

Truncation is not a soft cost here. A record whose prompt alone already exceeds
``max_seq_len`` contributes zero supervised signal (the assistant span — the only
part that carries loss — is entirely cut off) while still consuming a full
forward/backward. Records truncated mid-assistant teach the model to stop early.
So the two numbers that matter are reported separately:

- **total** tokens (prompt + assistant) — drives VRAM / throughput.
- **assistant** tokens — the completion the model must learn to emit; if this is
  clipped the label is corrupt.

With ``--tokenizer`` (a HF repo id or local path) the counts are exact, using
``apply_chat_template`` so the ``<|im_start|>`` scaffolding is included. Without
it, counts fall back to a CJK-aware character heuristic (see ``_heuristic_len``),
which is good to roughly +/-10% on this corpus — enough to choose between 512 /
1024 / 2048 / 4096, and clearly labelled as an estimate in the output.

Usage::

    inspect_sft_lengths.py                              # heuristic
    inspect_sft_lengths.py --tokenizer Qwen/Qwen3-8B    # exact
    inspect_sft_lengths.py --json                        # machine-readable
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from common import FINETUNE_ROOT, read_jsonl  # noqa: E402

SFT_DIR = FINETUNE_ROOT / "sft"
DATASETS = ("judge_c", "drafter_a")
SPLITS = ("train", "val")

# Candidate max_seq_len values to report overflow against. 512 is what M0 smoked.
THRESHOLDS = (512, 1024, 2048, 4096, 8192)

# Heuristic calibration for Qwen3-family BPE (151k vocab, strong CJK coverage):
# Chinese averages ~1.5 chars/token; ASCII prose ~3.5 chars/token.
CJK_TOKENS_PER_CHAR = 0.67
OTHER_TOKENS_PER_CHAR = 0.29
# <|im_start|>{role}\n ... <|im_end|>\n per message, x3 messages, + generation prompt.
CHATML_OVERHEAD = 16


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return (
        0x4E00 <= o <= 0x9FFF      # CJK unified ideographs
        or 0x3400 <= o <= 0x4DBF   # ext A
        or 0x3000 <= o <= 0x303F   # CJK punctuation
        or 0xFF00 <= o <= 0xFFEF   # fullwidth forms
    )


def _heuristic_len(text: str) -> int:
    cjk = sum(1 for ch in text if _is_cjk(ch))
    other = len(text) - cjk
    return int(cjk * CJK_TOKENS_PER_CHAR + other * OTHER_TOKENS_PER_CHAR)


def _pct(sorted_vals: list[int], q: float) -> int:
    if not sorted_vals:
        return 0
    i = min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) - 1))))
    return sorted_vals[i]


def _stats(vals: list[int]) -> dict:
    s = sorted(vals)
    return {
        "n": len(s),
        "min": s[0] if s else 0,
        "p50": _pct(s, 0.50),
        "p90": _pct(s, 0.90),
        "p95": _pct(s, 0.95),
        "p99": _pct(s, 0.99),
        "max": s[-1] if s else 0,
        "mean": int(sum(s) / len(s)) if s else 0,
    }


def _load_tokenizer(spec: str):
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(spec, trust_remote_code=True)


def _chat_template_len(tok, msgs: list[dict]) -> int:
    """Token count for the rendered ChatML conversation.

    ``apply_chat_template(tokenize=True)`` returns a bare list on transformers 4.x
    but a ``BatchEncoding`` on 5.x. ``BatchEncoding`` subclasses ``UserDict``, not
    ``dict``, so an ``isinstance(out, dict)`` guard silently misses it and
    ``len()`` then yields the number of keys (2) for every record.
    """
    out = tok.apply_chat_template(msgs, tokenize=True)
    if hasattr(out, "keys"):  # BatchEncoding / dict-like (transformers >=5)
        out = out["input_ids"]
    if out and isinstance(out[0], list):  # batched nesting
        out = out[0]
    return len(out)


def _measure(rows: list[dict], tok) -> tuple[list[int], list[int]]:
    """Return (total_lens, assistant_lens) for every record."""
    totals: list[int] = []
    assistants: list[int] = []
    for rec in rows:
        msgs = rec["messages"]
        assistant = next(
            (m["content"] for m in msgs if m["role"] == "assistant"), ""
        )
        if tok is not None:
            total = _chat_template_len(tok, msgs)
            a_len = len(tok(assistant, add_special_tokens=False)["input_ids"])
        else:
            total = (
                sum(_heuristic_len(m["content"]) for m in msgs) + CHATML_OVERHEAD
            )
            a_len = _heuristic_len(assistant)
        totals.append(total)
        assistants.append(a_len)
    return totals, assistants


def _overflow(totals: list[int], assistants: list[int]) -> list[dict]:
    """For each candidate max_seq_len: how much of the corpus survives intact."""
    out = []
    n = len(totals)
    for t in THRESHOLDS:
        clipped = sum(1 for x in totals if x > t)
        # prompt alone >= t means the assistant span is entirely gone -> zero signal
        dead = sum(1 for tot, a in zip(totals, assistants) if (tot - a) >= t)
        out.append({
            "max_seq_len": t,
            "fits": n - clipped,
            "truncated": clipped,
            "truncated_pct": round(100.0 * clipped / n, 1) if n else 0.0,
            "zero_signal": dead,
            "zero_signal_pct": round(100.0 * dead / n, 1) if n else 0.0,
        })
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sft-dir", default=str(SFT_DIR))
    ap.add_argument("--tokenizer", help="HF repo id or local path for exact counts")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args(argv)

    tok = None
    mode = "heuristic (CJK-aware char estimate, ~+/-10%)"
    if args.tokenizer:
        try:
            tok = _load_tokenizer(args.tokenizer)
            mode = f"exact ({args.tokenizer}, vocab={tok.vocab_size})"
        except Exception as exc:  # noqa: BLE001 - fall back rather than fail the run
            print(f"warning: tokenizer {args.tokenizer!r} unavailable "
                  f"({type(exc).__name__}: {exc}); falling back to heuristic",
                  file=sys.stderr)

    sft_dir = pathlib.Path(args.sft_dir)
    report: dict = {"mode": mode, "datasets": {}}

    for ds in DATASETS:
        rows: list[dict] = []
        for split in SPLITS:
            p = sft_dir / f"{ds}_{split}.jsonl"
            if p.exists():
                rows.extend(read_jsonl(p))
        if not rows:
            continue
        totals, assistants = _measure(rows, tok)
        report["datasets"][ds] = {
            "total_tokens": _stats(totals),
            "assistant_tokens": _stats(assistants),
            "overflow": _overflow(totals, assistants),
        }

    if not report["datasets"]:
        print(f"no SFT files under {sft_dir}; run export_sft_dataset.py all first")
        return 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print(f"token counting mode: {mode}")
    for ds, d in report["datasets"].items():
        t, a = d["total_tokens"], d["assistant_tokens"]
        print(f"\n=== {ds}  (n={t['n']}) ===")
        print(f"  total tokens      p50={t['p50']:>6}  p90={t['p90']:>6}  "
              f"p95={t['p95']:>6}  p99={t['p99']:>6}  max={t['max']:>6}")
        print(f"  assistant tokens  p50={a['p50']:>6}  p90={a['p90']:>6}  "
              f"p95={a['p95']:>6}  p99={a['p99']:>6}  max={a['max']:>6}")
        print(f"  {'max_seq_len':>12} {'fits':>7} {'truncated':>12} {'zero-signal':>14}")
        for row in d["overflow"]:
            print(f"  {row['max_seq_len']:>12} {row['fits']:>7} "
                  f"{row['truncated']:>7} ({row['truncated_pct']:>4}%) "
                  f"{row['zero_signal']:>7} ({row['zero_signal_pct']:>4}%)")

    # Recommendation: smallest threshold keeping >=95% of records intact, per dataset.
    print("\n--- recommendation ---")
    picks: dict[str, int] = {}
    for ds, d in report["datasets"].items():
        pick = next((r["max_seq_len"] for r in d["overflow"]
                     if r["truncated_pct"] <= 5.0), THRESHOLDS[-1])
        picks[ds] = pick
        print(f"  {ds}: max_seq_len >= {pick} keeps >=95% of records intact "
              f"(p99={d['total_tokens']['p99']}, max={d['total_tokens']['max']})")

    # A record whose prompt alone overflows carries no loss-bearing label at all.
    for ds, d in report["datasets"].items():
        at_512 = next(r for r in d["overflow"] if r["max_seq_len"] == 512)
        if at_512["zero_signal"]:
            print(f"  !! {ds}: at seq=512, {at_512['zero_signal']} records "
                  f"({at_512['zero_signal_pct']}%) lose their assistant span "
                  f"entirely — those train on nothing.")

    joint = max(picks.values()) if picks else 0
    if len(picks) > 1 and joint >= 2 * min(picks.values()):
        small = min(picks, key=lambda k: picks[k])
        n_small = report["datasets"][small]["total_tokens"]["n"]
        waste = joint // picks[small]
        print(f"\n  PREFER SEPARATE RUNS. A joint run at {joint} pads all "
              f"{n_small} {small} records (which need only {picks[small]}) to "
              f"{joint} — ~{waste}x the memory/compute per record for no gain.")
        for ds, p in picks.items():
            print(f"    - {ds}: seq={p}")
    else:
        print(f"  joint training run: max_seq_len = {joint}")

    if joint > 512:
        print(f"\n  NOTE: M0 smoked seq=512 at 26.6GB peak (18.5GB of that is the "
              f"static 4bit weights, so ~8GB was activations). Activation memory "
              f"scales with sequence length, so seq={joint} will not fit by "
              f"simply reusing the M0 batch size — re-smoke with gradient "
              f"checkpointing before fixing a batch size.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
