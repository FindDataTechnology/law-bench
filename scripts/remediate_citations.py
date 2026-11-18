#!/usr/bin/env python3
"""Remediation driver: dead-law citation fixes with records, snapshots, rollback.

Subcommands (see docs/law-catalog-runbook.md §引法修复):
  seed           (re)seed the successor map (explicit pairs + placeholders)
  dry-run        plan a batch (diff + evidence + skipped), print summary
  apply          apply a dry-run plan (update_clause only) + records/snapshots
  noaction       record reviewed-no-action citations (batch r0)
  rollback       restore a batch (optionally one clause) from before snapshots
  verify         re-run resolution+audit; report the closed loop
  export-paper   aggregate stats + before/after audit -> docs/ + JSONL
  export-finetune before->after correction pairs -> data/finetune/citation-fixes/

Usage:
  python scripts/remediate_citations.py dry-run --batch r1 --type sale --limit 50
  python scripts/remediate_citations.py apply    --batch r1 --type sale
  python scripts/remediate_citations.py rollback --batch r1 [--clause-id 113]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(override=True)

from src.law_catalog import audit, remediate, successor_seed  # noqa: E402


def _print_plan(plan: dict) -> None:
    print(json.dumps({
        "batch": plan["batch"],
        "apply_candidates": len(plan["apply"]),
        "skipped_review": len(plan["skipped_review"]),
        "needs_human": len(plan["needs_human"]),
    }, ensure_ascii=False))
    for item in plan["apply"][:5]:
        reps = [f"《{r['before'].strip('《》')}》→{r['after'].strip('《》')}" for r in item["replacements"]]
        print(f"  #{item['clause_id']} [{item['contract_type']}] {'; '.join(reps)}")
    if plan["apply"]:
        print("  …（完整清单见 dry-run --json 输出）")
    for item in plan["skipped_review"][:5]:
        print(f"  SKIP #{item['clause_id']}: {item.get('reason') or '叙述白名单'}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("dry-run", "apply"):
        sp = sub.add_parser(name)
        sp.add_argument("--batch", required=True)
        sp.add_argument("--type", help="limit to one contract_type")
        sp.add_argument("--limit", type=int)
        sp.add_argument("--json", action="store_true", help="dump full plan as JSON")
    sub.add_parser("seed")
    sp = sub.add_parser("noaction"); sp.add_argument("--batch", default="r0")
    sp = sub.add_parser("rollback"); sp.add_argument("--batch", required=True); sp.add_argument("--clause-id", type=int)
    sub.add_parser("verify")
    sub.add_parser("export-paper")
    sp = sub.add_parser("export-finetune"); sp.add_argument("--batch", required=True)
    args = ap.parse_args()

    if args.cmd == "seed":
        print(json.dumps(successor_seed.seed_successor_map(), ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "dry-run":
        plan = remediate.plan_batch(args.batch, contract_type=args.type, limit=args.limit)
        if args.json:
            print(json.dumps(plan, ensure_ascii=False, indent=1, default=str))
        else:
            _print_plan(plan)
        return 0
    if args.cmd == "apply":
        plan = remediate.plan_batch(args.batch, contract_type=args.type, limit=args.limit)
        print(json.dumps(remediate.apply_batch(plan), ensure_ascii=False))
        print(json.dumps(remediate.verify_batch(), ensure_ascii=False))
        return 0
    if args.cmd == "noaction":
        print(json.dumps(remediate.record_no_action(args.batch), ensure_ascii=False))
        return 0
    if args.cmd == "rollback":
        print(json.dumps(remediate.rollback_batch(args.batch, clause_id=args.clause_id), ensure_ascii=False))
        print(json.dumps(remediate.verify_batch(), ensure_ascii=False))
        return 0
    if args.cmd == "verify":
        print(json.dumps(remediate.verify_batch(), ensure_ascii=False))
        return 0
    if args.cmd == "export-paper":
        result = audit.collect_audit()
        from src.eval.db import connect
        conn = connect()
        rows = conn.execute(
            "SELECT disposition, contract_type, count(*) n FROM law_catalog.citation_revisions "
            "GROUP BY 1,2 ORDER BY 1,3 DESC").fetchall()
        conn.close()
        out = {"audit": result["summary"],
               "revisions": [dict(r) for r in rows]}
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "export-finetune":
        from src.eval.db import connect
        conn = connect()
        rows = conn.execute(
            "SELECT v.cited_before, v.cited_after, v.contract_type, "
            "ld.title AS dead_title, ls.title AS successor_title "
            "FROM law_catalog.citation_revisions v "
            "LEFT JOIN law_catalog.laws ld ON ld.id = v.dead_law_id "
            "LEFT JOIN law_catalog.laws ls ON ls.id = v.successor_law_id "
            "WHERE v.batch = %s AND v.disposition = 'applied' ORDER BY v.clause_id",
            (args.batch,)).fetchall()
        conn.close()
        outdir = Path("data/finetune/citation-fixes")
        outdir.mkdir(parents=True, exist_ok=True)
        out = outdir / f"{args.batch}.jsonl"
        with out.open("w", encoding="utf-8", newline="\n") as f:
            for r in rows:
                f.write(json.dumps({
                    "task": "citation-correction",
                    "before": r["cited_before"],
                    "after": r["cited_after"],
                    "contract_type": r["contract_type"],
                    "reason": f"{r['dead_title']} 已废止，承继法为 {r['successor_title']}",
                }, ensure_ascii=False) + "\n")
        print(f"exported {len(rows)} pairs -> {out}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
