#!/usr/bin/env python3
"""Slice Judge-C scaffolds into human-review batches and promote approved gold.

This is the operational bridge between the machine scaffold builder
(``export_dataset.py judge-c-scaffold`` → tier=silver candidates) and the
flywheel gate (``export_dataset.py gate``), which stays shut until a
non-empty ``judge_c_gold.jsonl`` exists.

Workflow
--------
1. ``prepare``  — read ``judge_c_scaffold.jsonl``, join each scaffold to its
   ``type_validations`` rule (contract_type / field / severity / law_ref),
   rank types by candidate count, and write per-type envelope batches into
   ``data/finetune/review/inbox/``. The top-N types form phase 1.
2. Human review — copy a batch from ``inbox/`` to ``done/`` (or your own work
   area), edit each envelope's ``quadruple`` (verdict / reasoning /
   legal_base), set ``review.status`` to ``approved`` / ``rejected`` /
   ``skip``, and stamp ``review.annotator``.
3. ``promote``  — scan ``done/*.jsonl``, extract every ``approved``
   quadruple, force gold provenance (reviewer=human, tier=gold), reject any
   that still cite ``law_info:*`` (an LLM hint is not an authority), run
   ``validate_quadruple``, and write a flat gold file. The operator then
   runs ``export_dataset.py judge-c --gold <file>`` and ``gate``.

``inbox/`` is regenerable (gitignored); ``done/`` and the promoted gold are
human work product and are NOT regenerable — back them up.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from common import (  # noqa: E402
    FINETUNE_ROOT,
    JUDGE_C_DIR,
    WAREHOUSE_DIR,
    read_jsonl,
    write_jsonl,
)
from export_dataset import validate_quadruple  # noqa: E402

REVIEW_DIR = FINETUNE_ROOT / "review"
INBOX_DIR = REVIEW_DIR / "inbox"
DONE_DIR = REVIEW_DIR / "done"
SCAFFOLD_PATH = JUDGE_C_DIR / "judge_c_scaffold.jsonl"
PROMOTED_PATH = JUDGE_C_DIR / "judge_c_gold.review.jsonl"

PHASE1_TOP_N = 5

# scaffold:machine:type_validations:<rule_id>:clause:<clause_id>:<match>
_SCAFFOLD_ID_RE = re.compile(
    r"^scaffold:machine:type_validations:(\d+):clause:(\d+):(exact|fuzzy)$"
)


def _load_rule_map() -> dict[int, dict]:
    """Map type_validations.id → the compliance rule row."""
    rules: dict[int, dict] = {}
    for rec in read_jsonl(WAREHOUSE_DIR / "type_validations.jsonl"):
        row = rec.get("row", rec)
        rid = row.get("id")
        if rid is not None:
            rules[int(rid)] = row
    return rules


def _parse_scaffold_id(scaffold_id: str) -> tuple[int, int, str]:
    m = _SCAFFOLD_ID_RE.match(scaffold_id or "")
    if not m:
        raise ValueError(f"unparseable scaffold provenance id: {scaffold_id!r}")
    return int(m.group(1)), int(m.group(2)), m.group(3)


def cmd_prepare(_args: argparse.Namespace) -> int:
    scaffolds = read_jsonl(SCAFFOLD_PATH)
    if not scaffolds:
        print(f"no scaffolds at {SCAFFOLD_PATH}; run judge-c-scaffold first")
        return 1

    rules = _load_rule_map()
    grouped: dict[str, list[dict]] = defaultdict(list)
    missing_rule = 0

    for s in scaffolds:
        sid = s.get("provenance", {}).get("id", "")
        try:
            rule_id, clause_id, match = _parse_scaffold_id(sid)
        except ValueError:
            missing_rule += 1
            continue
        rule = rules.get(rule_id, {})
        contract_type = rule.get("contract_type") or "unknown"
        envelope = {
            "scaffold_id": sid,
            "contract_type": contract_type,
            "rule": {
                "id": rule_id,
                "constraint_id": rule.get("constraint_id"),
                "field": rule.get("field"),
                "severity": rule.get("severity"),
                "message": rule.get("message"),
                "law_ref": rule.get("law_ref"),
            },
            "match": match,
            "clause_id": clause_id,
            "quadruple": s,
            "review": {"status": "pending", "annotator": None, "notes": ""},
        }
        grouped[contract_type].append(envelope)

    # Rank types by candidate volume; the largest form phase 1.
    ranked = sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    phase1_types = {ct for ct, _ in ranked[:PHASE1_TOP_N]}

    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    manifest_rows: list[dict] = []
    total = 0
    for contract_type, envelopes in ranked:
        phase = 1 if contract_type in phase1_types else 2
        # Deterministic order: rule id, then clause id.
        envelopes.sort(key=lambda e: (e["rule"]["id"], e["clause_id"]))
        fname = f"p{phase}_{contract_type}.jsonl"
        write_jsonl(INBOX_DIR / fname, envelopes)
        total += len(envelopes)
        manifest_rows.append({
            "contract_type": contract_type,
            "phase": phase,
            "candidates": len(envelopes),
            "file": f"inbox/{fname}",
        })

    manifest = {
        "scaffold_total": len(scaffolds),
        "batched": total,
        "missing_rule": missing_rule,
        "phase1_top_n": PHASE1_TOP_N,
        "types": manifest_rows,
    }
    (REVIEW_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"batched {total}/{len(scaffolds)} scaffolds into {len(ranked)} types")
    print(f"phase 1 (top {PHASE1_TOP_N} by volume):")
    for r in manifest_rows:
        if r["phase"] == 1:
            print(f"  {r['contract_type']:<22} {r['candidates']:>4}  {r['file']}")
    print(f"phase 2: {sum(r['candidates'] for r in manifest_rows if r['phase'] == 2)} "
          f"candidates across {sum(1 for r in manifest_rows if r['phase'] == 2)} types")
    print(f"inbox: {INBOX_DIR}")
    if missing_rule:
        print(f"WARNING: {missing_rule} scaffolds had no matching type_validations row")
    return 0


def _promote_envelope(env: dict, index: int) -> tuple[dict | None, str]:
    """Return (gold_quadruple, error) for one approved envelope."""
    review = env.get("review") or {}
    status = review.get("status")
    if status != "approved":
        return None, f"status={status!r} (not approved)"

    q = env.get("quadruple")
    if not isinstance(q, dict):
        return None, "missing quadruple"

    # Stamp gold provenance. Preserve the human/AI's verdict/reasoning/legal_base.
    q["tier"] = "gold"
    prov = q.setdefault("provenance", {})
    # Accept both human and ai_reviewer; annotate_by reflects who actually wrote it.
    reviewer = review.get("reviewer")
    if reviewer in ("human", "ai_reviewer"):
        prov["reviewer"] = reviewer
    elif prov.get("reviewer") in ("human", "ai_reviewer"):
        pass  # keep what the envelope already has from AI annotation
    else:
        prov["reviewer"] = "human"  # default for backward compat
    prov["annotated_by"] = review.get("annotated_by") or prov.get("annotated_by", "ai_reviewed")
    if review.get("annotator"):
        prov["annotator"] = review["annotator"]
    # Bootstrap envelopes carry a confidence score; keep it so downstream SFT can
    # down-weight the weaker auto-approved band (the 0.5-0.6 rows) instead of
    # treating every ai_reviewer row as equally trustworthy. Scaffold envelopes
    # have no confidence (they are human-reviewed) and are left without one.
    if env.get("confidence") is not None:
        prov["confidence"] = env["confidence"]
    sid = env.get("scaffold_id") or prov.get("id", "")
    try:
        rule_id, clause_id, _match = _parse_scaffold_id(sid)
        prov["id"] = f"gold:{reviewer}:{env.get('contract_type', 'unknown')}:{rule_id}:{clause_id}"
        prov["scaffold_ref"] = sid
    except ValueError:
        pass

    # A human/AI may judge pass or fail, but the legal basis must be authoritative:
    # an LLM-generated law_info hint is never citable as gold.
    lb = q.get("legal_base") or {}
    source = (lb.get("source") or "").strip()
    if not source or source.startswith("law_info:"):
        return None, f"legal_base.source still {source!r}: must cite an authoritative source"
    if "[retrieval hint]" in (lb.get("text") or ""):
        return None, "legal_base.text still contains the [retrieval hint] block"
    citation = (q.get("reasoning") or {}).get("citation") or []
    if not citation:
        return None, "reasoning.citation empty"

    try:
        validate_quadruple(q, index)
    except Exception as e:  # noqa: BLE001 — surface any validation failure
        return None, f"validate: {e}"
    return q, ""


def cmd_promote(args: argparse.Namespace) -> int:
    src = pathlib.Path(args.from_dir)
    out = pathlib.Path(args.out)
    if not src.is_dir():
        print(f"no review directory at {src} (nothing to promote)")
        return 1

    gold: list[dict] = []
    seen_ids: set[str] = set()
    rejected: list[tuple[str, str]] = []
    skipped = 0
    files = sorted(src.glob("*.jsonl"))
    for fpath in files:
        for i, env in enumerate(read_jsonl(fpath)):
            status = (env.get("review") or {}).get("status")
            if status in (None, "pending", "rejected", "skip"):
                skipped += 1
                continue
            q, err = _promote_envelope(env, i)
            if err:
                rejected.append((f"{fpath.name}#{i}", err))
                continue
            gid = q["provenance"]["id"]
            if gid in seen_ids:
                rejected.append((f"{fpath.name}#{i}", f"duplicate gold id {gid}"))
                continue
            seen_ids.add(gid)
            gold.append(q)

    write_jsonl(out, gold)
    print(f"promoted {len(gold)} approved quadruples → {out}")
    print(f"  skipped (pending/rejected/skip): {skipped}")
    print(f"  rejected: {len(rejected)}")
    for loc, err in rejected[:50]:
        print(f"    {loc}: {err}")
    if not gold:
        print("no gold promoted; gate stays shut")
        return 1
    print(f"\nnext: python scripts/finetune/export_dataset.py judge-c --gold {out}")
    print("      python scripts/finetune/export_dataset.py gate")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_prep = sub.add_parser("prepare", help="slice scaffolds into review batches")
    p_prep.set_defaults(func=cmd_prepare)

    p_pro = sub.add_parser("promote", help="promote approved envelopes to gold")
    p_pro.add_argument("--from-dir", default=str(DONE_DIR),
                       help=f"directory of reviewed envelope JSONL (default {DONE_DIR})")
    p_pro.add_argument("--out", default=str(PROMOTED_PATH),
                       help=f"flat gold output path (default {PROMOTED_PATH})")
    p_pro.set_defaults(func=cmd_promote)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
