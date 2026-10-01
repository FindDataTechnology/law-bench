"""Curate sale's tagged clauses into diff-based scenario overrides.

For each (scenario, section) group of tagged clauses:
1. Compare each clause body to the 母版 (base) body for the same section
   (difflib SequenceMatcher ratio). If a clause is near-duplicate of the 母版
   (ratio >= --threshold), it is discarded - the base already covers that section.
2. Among the remaining (genuinely different) clauses, collapse to one per
   (scenario, section) by the tiebreak (most slots -> longest body -> lowest id).
3. Sections absent from the 母版 are kept as extensions (no base to diff against).

Result: at most one tagged override per (scenario, section), only for sections
that genuinely differ from the 母版. Discarded clause ids are listed for deletion.

Rollback snapshot -> output/_sale_curate_rollback.json (full rows deleted).

Usage:
  PYTHONPATH=. python3 scripts/curate_sale_overrides.py --dry-run
  PYTHONPATH=. python3 scripts/curate_sale_overrides.py --threshold 0.7 --apply
"""
from __future__ import annotations
import argparse, json
from difflib import SequenceMatcher
from src.eval.db import connect
from src.contracts.templates import list_contract_types

CONTRACT_TYPE = "sale"


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.7, help="discard if ratio >= threshold")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not (args.dry_run or args.apply):
        ap.error("pass --dry-run or --apply")

    conn = connect()
    conn.autocommit = True  # set before any query so DELETEs are per-statement
    # 母版 base bodies per section
    base = {r["section"]: r["body"] for r in conn.execute(
        "SELECT section, body FROM clauses WHERE contract_type=%s AND tags->>'source'='base'", (CONTRACT_TYPE,)
    ).fetchall()}
    # tagged clauses with a scenario
    rows = conn.execute(
        "SELECT id, section, body, tags, slot_instructions, law_refs, source_path, source_doc_title, manual "
        "FROM clauses WHERE contract_type=%s AND tags->>'source'='tagged' AND tags->>'scenario' IS NOT NULL ORDER BY id",
        (CONTRACT_TYPE,),
    ).fetchall()

    import re
    slot_re = re.compile(r"\{\{(\w+)\}\}")

    from collections import defaultdict
    groups = defaultdict(list)  # (scenario, section) -> [row]
    for r in rows:
        groups[(r["tags"]["scenario"], r["section"])].append(r)

    keep_ids, discard_ids = set(), set()
    diff_kept = ext_kept = 0
    for (scen, sec), cands in groups.items():
        base_body = base.get(sec)
        if base_body is None:
            # extension: no base to diff -> keep best one
            ext_kept += 1
            best = max(cands, key=lambda c: (len(set(slot_re.findall(c["body"]))), len(c["body"]), -c["id"]))
            keep_ids.add(best["id"])
            for c in cands:
                if c["id"] != best["id"]:
                    discard_ids.add(c["id"])
            continue
        # diff: keep only clauses genuinely different from 母版
        different = [c for c in cands if _ratio(c["body"], base_body) < args.threshold]
        if not different:
            # all near-duplicate of base -> discard all (base covers it)
            for c in cands:
                discard_ids.add(c["id"])
            continue
        diff_kept += 1
        best = max(different, key=lambda c: (len(set(slot_re.findall(c["body"]))), len(c["body"]), -c["id"]))
        keep_ids.add(best["id"])
        for c in cands:
            if c["id"] != best["id"]:
                discard_ids.add(c["id"])

    print(f"threshold={args.threshold}  tagged clauses={len(rows)}  groups={len(groups)}")
    print(f"  keep={len(keep_ids)} (diff_kept={diff_kept}, extension_kept={ext_kept})  discard={len(discard_ids)}")

    if args.apply:
        rollback = [dict(r) for r in rows if r["id"] in discard_ids]
        # convert jsonb (already dict/list) - fine for json.dump
        for r in rollback:
            r["tags"] = dict(r["tags"])
        json.dump(rollback, open("output/_sale_curate_rollback.json", "w"), ensure_ascii=False, indent=1)
        for cid in discard_ids:
            conn.execute("DELETE FROM clauses WHERE id=%s", (cid,))
        print(f"[applied] deleted {len(discard_ids)} clauses; rollback -> output/_sale_curate_rollback.json")
    conn.close()


if __name__ == "__main__":
    main()
