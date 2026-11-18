#!/usr/bin/env python3
"""Export SFT-ready training files in ChatML format from M1's structured data.

Reads the gold Judge-C quadruples and silver Drafter-A pairs produced by
``export_dataset.py`` and ``prepare_review_batches.py`` and writes
``data/finetune/sft/{judge_c,drafter_a}_{train,val}.jsonl`` with the shape::

    {"_meta": {...}, "messages": [
        {"role": "system", "content": "..."},
        {"role": "user",   "content": "..."},
        {"role": "assistant", "content": "..."}
    ]}

The ``messages`` shape is the canonical Qwen3 ChatML input; let
``tokenizer.apply_chat_template`` wrap the actual ``<|im_start|>`` markers.
``_meta`` is opaque to the trainer (it gets dropped before tokenization) but
keeps each record self-describing for downstream debugging / sample-weighting.

Train/val split: random 90/10 with fixed seed ``SPLIT_SEED=42``. Re-runnable,
deterministic, not per-rubric stratified (42 rubrics × 1969 rows means most
strata have <5 records, where stratification starves the val set).

The output ``data/finetune/sft/manifest.json`` IS tracked (small, stable,
useful in PR review). The four ``.jsonl`` files are regenerable and
gitignored.

Subcommands::

    export_sft_dataset.py judge-c   [--gold PATH]  [--out-dir PATH]
    export_sft_dataset.py drafter-a [--silver PATH] [--out-dir PATH]
    export_sft_dataset.py all
    export_sft_dataset.py manifest
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import pathlib
import random
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from common import (  # noqa: E402
    DRAFTER_A_DIR,
    FINETUNE_ROOT,
    JUDGE_C_DIR,
    read_jsonl,
    write_jsonl,
)

SPLIT_SEED = 42
VAL_FRACTION = 0.10
SFT_DIR = FINETUNE_ROOT / "sft"

# ----------------------------------------------------------------------------
# prompt templates — keep natural distribution. The judge's clause_text is
# English (model historical narrative); legal_base is Chinese (human rubric).
# Translating would manufacture signal that wasn't in the gold.
# ----------------------------------------------------------------------------

JUDGE_C_SYSTEM = (
    "你是一名合同合规审查员，对照给定法条/规则审查条款正文，"
    "输出 pass/fail 判决及法律推理。"
)

# `legal_base.source` (the criterion handle, e.g. "criteria:price_difference
# (rubric:contract_brokerage_v2)") IS rendered. Without it the target
# `citation` string appeared verbatim in the prompt in only 14/1773 records
# (0.8%) — a 191-way identifier the model could only memorize, and since every
# val citation was also seen in train, val would have measured memorization
# rather than generalization. The caller always knows which criterion it asked
# about, so supplying it is legitimate grounding, not leakage.
JUDGE_C_USER_TEMPLATE = (
    "【审查依据】{legal_base_source}\n{legal_base_text}\n\n"
    "【待审合同正文】\n{clause_text_body}\n\n"
    "请按 JSON 输出：{{\"verdict\": \"pass|fail\", "
    "\"justification\": \"...\", \"citation\": [\"...\"]}}"
)

DRAFTER_A_SYSTEM = (
    "你是一名中国合同起草律师，按客户需求起草合同正文。"
)

DRAFTER_A_USER_TEMPLATE = (
    "{task_desc}\n\n"
    "【槽位值】\n{slot_lines}"
)


# ----------------------------------------------------------------------------
# core conversions
# ----------------------------------------------------------------------------

def _split_indices(n: int, seed: int, val_frac: float) -> tuple[set[int], set[int]]:
    """Return (train_indices, val_indices) via a seeded shuffle.

    Re-runnable, deterministic, and stable for the same (n, seed) pair.
    """
    rng = random.Random(seed)
    idx = list(range(n))
    rng.shuffle(idx)
    cut = int(n * val_frac)
    val = set(idx[:cut])
    train = set(idx[cut:])
    return train, val


def _split_indices_stratified(
    rows: list[dict], seed: int, val_frac: float, group_key
) -> tuple[set[int], set[int]]:
    """Stance-stratified split (spec delta: 验证集按立场分层).

    Each group contributes ``ceil(n*val_frac)`` val rows (at least 1 when the
    group has >=2 rows, never all of them), so a minority stance never lands
    entirely on one side. Per-group RNG is seeded from ``(seed, group)`` —
    ``random.Random`` hashes str seeds via sha512, stable across runs and
    platforms. Groups with a single row go to train (learning signal wins
    over val coverage when both are impossible).
    """
    groups: dict[str, list[int]] = {}
    for i, row in enumerate(rows):
        groups.setdefault(group_key(row), []).append(i)
    train: set[int] = set()
    val: set[int] = set()
    for group in sorted(groups):
        idx = list(groups[group])
        if len(idx) == 1:
            train.update(idx)
            continue
        rng = random.Random(f"{seed}:{group}")
        rng.shuffle(idx)
        cut = max(1, math.ceil(len(idx) * val_frac))
        cut = min(cut, len(idx) - 1)  # train side keeps >=1 row per group
        val.update(idx[:cut])
        train.update(idx[cut:])
    return train, val


def _format_slots(slots: list[dict]) -> str:
    if not slots:
        return "（无显式槽位）"
    lines = []
    for s in slots:
        name = s.get("name", "?")
        val = s.get("value", "")
        if val:
            lines.append(f"- {name}: {val}")
        else:
            lines.append(f"- {name}: （待补）")
    return "\n".join(lines)


def _judge_c_to_chatml(row: dict) -> dict:
    lb = row.get("legal_base", {}) or {}
    ct = row.get("clause_text", {}) or {}
    rs = row.get("reasoning", {}) or {}
    prov = row.get("provenance", {}) or {}

    user = JUDGE_C_USER_TEMPLATE.format(
        legal_base_source=lb.get("source", "").strip(),
        legal_base_text=lb.get("text", "").strip(),
        clause_text_body=(ct.get("body") or "").strip(),
    )
    # Assistant: single-line JSON, exactly the shape the original model emitted.
    assistant_obj = {
        "verdict": row.get("verdict", "fail"),
        "justification": (rs.get("justification") or "").strip(),
        "citation": list(rs.get("citation") or []),
    }
    assistant = json.dumps(assistant_obj, ensure_ascii=False, sort_keys=True)
    return {
        "messages": [
            {"role": "system", "content": JUDGE_C_SYSTEM},
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ],
    }


def _drafter_a_to_chatml(row: dict) -> dict:
    user = DRAFTER_A_USER_TEMPLATE.format(
        task_desc=(row.get("task_desc") or "").strip(),
        slot_lines=_format_slots(row.get("slots") or []),
    )
    return {
        "messages": [
            {"role": "system", "content": DRAFTER_A_SYSTEM},
            {"role": "user", "content": user},
            {"role": "assistant", "content": (row.get("body") or "").strip()},
        ],
    }


def _add_meta(chatml: dict, row: dict, split: str, kind: str) -> dict:
    prov = row.get("provenance", {}) or {}
    meta = {
        "kind": kind,
        "tier": row.get("tier"),
        "split": split,
        "split_seed": SPLIT_SEED,
        "provenance_id": prov.get("id"),
        "reviewer": prov.get("reviewer"),
        "annotated_by": prov.get("annotated_by"),
        "contract_path": prov.get("contract_path"),
    }
    if kind == "judge-c":
        meta["verdict"] = row.get("verdict")
        # Present on bootstrap-derived gold only; lets the trainer down-weight the
        # weaker auto-approved band rather than trusting all ai_reviewer rows equally.
        if prov.get("confidence") is not None:
            meta["confidence"] = prov["confidence"]
    else:
        # drafter-a: record contract_type/scenario/stance for downstream filtering
        meta["contract_type"] = prov.get("contract_type")
        meta["scenario"] = prov.get("scenario")
        meta["stance"] = prov.get("stance")
        # Dual-source bookkeeping (spec delta: 清单按源分计): source from the
        # provenance id table prefix (pipeline_runs / contract_artifacts).
        meta["source"] = (prov.get("id") or "").split(":", 1)[0] or None
        meta["synthetic_slots"] = bool(prov.get("synthetic_slots"))
        # Quality metadata on pipeline-sourced pairs only (design D4).
        if prov.get("score_ratio") is not None:
            meta["score_ratio"] = prov["score_ratio"]
    return {"_meta": meta, **chatml}


# ----------------------------------------------------------------------------
# subcommands
# ----------------------------------------------------------------------------

def _write_split(
    rows: list[dict],
    train_idx: set[int],
    val_idx: set[int],
    out_dir: pathlib.Path,
    name: str,
    to_chatml,
) -> dict:
    """Write {name}_train.jsonl + {name}_val.jsonl, return counts."""
    train_path = out_dir / f"{name}_train.jsonl"
    val_path = out_dir / f"{name}_val.jsonl"
    train_rows: list[dict] = []
    val_rows: list[dict] = []
    for i, row in enumerate(rows):
        split = "val" if i in val_idx else "train"
        chatml = to_chatml(row)
        rec = _add_meta(chatml, row, split, kind=name.replace("_", "-"))
        (val_rows if split == "val" else train_rows).append(rec)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(train_path, train_rows)
    write_jsonl(val_path, val_rows)
    return {
        "total": len(rows),
        "train": len(train_rows),
        "val": len(val_rows),
        "train_path": str(train_path),
        "val_path": str(val_path),
        "tier_breakdown": dict(Counter(r["tier"] for r in rows if r.get("tier"))),
        "verdict_breakdown": dict(
            Counter(r.get("verdict") for r in rows if r.get("verdict"))
        ) if any(r.get("verdict") for r in rows) else None,
    }


def cmd_judge_c(args: argparse.Namespace) -> int:
    if args.gold:
        gold_path = pathlib.Path(args.gold)
    else:
        # Default to the regrounded set. The raw judge_c_gold.jsonl has
        # clause_text.body lifted from reasoning.justification in 96% of rows
        # (see reground_judge_c.py), so training on it teaches paraphrasing
        # rather than judging. Requiring an explicit --gold to reach it means
        # nobody trains on the leaked set by accident.
        gold_path = JUDGE_C_DIR / "judge_c_gold.grounded.jsonl"
        if not gold_path.exists():
            print(f"missing regrounded gold at {gold_path}\n"
                  "run: python scripts/finetune/reground_judge_c.py build\n"
                  "(to export the leaked set anyway, pass --gold explicitly)")
            return 1
    rows = read_jsonl(gold_path)
    if not rows:
        print(f"no gold quadruples at {gold_path}")
        return 1
    train_idx, val_idx = _split_indices(len(rows), SPLIT_SEED, VAL_FRACTION)
    counts = _write_split(rows, train_idx, val_idx,
                          pathlib.Path(args.out_dir), "judge_c", _judge_c_to_chatml)
    print(f"judge-c: {counts['total']} -> train {counts['train']} + val {counts['val']} "
          f"(seed={SPLIT_SEED}, val_frac={VAL_FRACTION})")
    print(f"  tier: {counts['tier_breakdown']}")
    if counts['verdict_breakdown']:
        print(f"  verdict: {counts['verdict_breakdown']}")
    print(f"  out: {counts['train_path']}\n       {counts['val_path']}")
    return 0


def cmd_drafter_a(args: argparse.Namespace) -> int:
    silver_path = pathlib.Path(args.silver) if args.silver else DRAFTER_A_DIR / "drafter_a_silver.jsonl"
    rows = read_jsonl(silver_path)
    if not rows:
        print(f"no silver pairs at {silver_path}")
        return 1
    # Stance-stratified split (spec delta): minority stances must appear on
    # both sides. Judge-C keeps the plain random split above.
    train_idx, val_idx = _split_indices_stratified(
        rows, SPLIT_SEED, VAL_FRACTION,
        group_key=lambda r: (r.get("provenance") or {}).get("stance") or "(untagged)",
    )
    counts = _write_split(rows, train_idx, val_idx,
                          pathlib.Path(args.out_dir), "drafter_a", _drafter_a_to_chatml)
    print(f"drafter-a: {counts['total']} -> train {counts['train']} + val {counts['val']} "
          f"(seed={SPLIT_SEED}, val_frac={VAL_FRACTION}, stance-stratified)")
    print(f"  tier: {counts['tier_breakdown']}")
    print(f"  out: {counts['train_path']}\n       {counts['val_path']}")
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    rc1 = cmd_judge_c(argparse.Namespace(
        out_dir=args.out_dir,
        gold=getattr(args, "gold", None),
    ))
    print()
    rc2 = cmd_drafter_a(argparse.Namespace(
        out_dir=args.out_dir,
        silver=getattr(args, "silver", None),
    ))
    print()
    rc3 = cmd_manifest(argparse.Namespace(out_dir=args.out_dir))
    return rc1 or rc2 or rc3


def cmd_manifest(args: argparse.Namespace) -> int:
    out_dir = pathlib.Path(args.out_dir)
    counts: dict[str, dict] = {}
    sources: dict[str, str] = {}

    jc_train = out_dir / "judge_c_train.jsonl"
    jc_val = out_dir / "judge_c_val.jsonl"
    if jc_train.exists() and jc_val.exists():
        train = read_jsonl(jc_train)
        val = read_jsonl(jc_val)
        meta_all = [r["_meta"] for r in train + val]
        confs = [m["confidence"] for m in meta_all if m.get("confidence") is not None]
        counts["judge_c"] = {
            "total": len(train) + len(val),
            "train": len(train),
            "val": len(val),
            "tier_breakdown": dict(Counter(m.get("tier") for m in meta_all)),
            "reviewer_breakdown": dict(Counter(m.get("reviewer") for m in meta_all)),
            "verdict_breakdown": dict(Counter(m.get("verdict") for m in meta_all)),
            # The auto-approve floor is 0.5; the 0.5-0.6 band is the weaker tail
            # worth down-weighting rather than dropping.
            "confidence_bands": dict(Counter(
                "0.5-0.6" if c < 0.6 else "0.6-0.8" if c < 0.8 else ">=0.8"
                for c in confs
            )) if confs else None,
        }
        sources["judge_c"] = str(JUDGE_C_DIR / "judge_c_gold.grounded.jsonl")

    da_train = out_dir / "drafter_a_train.jsonl"
    da_val = out_dir / "drafter_a_val.jsonl"
    if da_train.exists() and da_val.exists():
        train = read_jsonl(da_train)
        val = read_jsonl(da_val)
        meta_all = [r["_meta"] for r in train + val]
        # Dual-source bookkeeping (spec delta: 清单按源分计 + 质量元数据可见).
        src_names = [m.get("source") or "(unknown)" for m in meta_all]
        ratios = [m["score_ratio"] for m in meta_all if m.get("score_ratio") is not None]
        counts["drafter_a"] = {
            "total": len(train) + len(val),
            "train": len(train),
            "val": len(val),
            "tier_breakdown": dict(Counter(m.get("tier") for m in meta_all)),
            "source_breakdown": dict(Counter(src_names)),
            "synthetic_count": sum(1 for m in meta_all if m.get("synthetic_slots")),
            # Eval-score bands of the pipeline-sourced drafts: the trainer can
            # down-weight the weak tail instead of trusting all silver equally.
            "score_ratio_bands": dict(Counter(
                ">=0.8" if r >= 0.8 else "0.5-0.8" if r >= 0.5 else "<0.5"
                for r in ratios
            )) if ratios else None,
            # Surfaced because the skew is the main known weakness of this pool:
            # stance=balanced dominates and pro_a/pro_b is a handful of rows.
            "stance_breakdown": dict(Counter(
                m.get("stance") or "(untagged)" for m in meta_all
            )),
            "contract_type_breakdown": dict(Counter(
                m.get("contract_type") or "(untagged)" for m in meta_all
            ).most_common()),
        }
        sources["drafter_a"] = str(DRAFTER_A_DIR / "drafter_a_silver.jsonl")

    if not counts:
        print(f"no SFT files found under {out_dir}; run 'all' or 'judge-c' / 'drafter-a' first")
        return 1

    manifest = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "seed": SPLIT_SEED,
        "val_fraction": VAL_FRACTION,
        "format": "ChatML {system, user, assistant}",
        "counts": counts,
        "sources": sources,
    }
    out_path = out_dir / "manifest.json"
    out_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"manifest: {out_path}")
    print(f"  judge_c:  total={counts['judge_c']['total']}  "
          f"train={counts['judge_c']['train']}  val={counts['judge_c']['val']}")
    print(f"  drafter_a: total={counts['drafter_a']['total']}  "
          f"train={counts['drafter_a']['train']}  val={counts['drafter_a']['val']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--out-dir", default=str(SFT_DIR), help="output directory (default data/finetune/sft)")

    p_jc = sub.add_parser("judge-c", parents=[common], help="export Judge-C quadruples → ChatML")
    p_jc.add_argument("--gold", help="path to judge_c_gold.jsonl (default canonical)")
    p_jc.set_defaults(func=cmd_judge_c)

    p_da = sub.add_parser("drafter-a", parents=[common], help="export Drafter-A pairs → ChatML")
    p_da.add_argument("--silver", help="path to drafter_a_silver.jsonl (default canonical)")
    p_da.set_defaults(func=cmd_drafter_a)

    p_all = sub.add_parser("all", parents=[common], help="export both + write manifest")
    p_all.set_defaults(func=cmd_all)

    p_man = sub.add_parser("manifest", parents=[common], help="(re)write manifest.json from existing train/val files")
    p_man.set_defaults(func=cmd_manifest)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
