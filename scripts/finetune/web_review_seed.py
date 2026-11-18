#!/usr/bin/env python3
"""Create web human-review batches from eval history (change add-web-human-review).

Samples ``eval_criteria_results`` rows (joined to ``eval_runs`` for the rubric and
contract type) into ``review_tasks`` rows the web UI serves at ``/review``. The
run selection is an operator decision: ``--list-runs`` shows what is in the
database (rubric, date, size), then you pin the ids you want with ``--run-ids``.

Examples
--------
    # what is available, newest first
    python scripts/finetune/web_review_seed.py --list-runs --rubric-regex '^contract_'

    # 3 criteria per contract type, 2 annotator slots each, from the pinned V4 runs
    python scripts/finetune/web_review_seed.py --batch-id v4-validity-pilot \
        --batch-type validity --run-ids 101,102,103 --per-type 3 --annotators 2

Re-running with the same ``--batch-id`` is a no-op (``create_batch`` is
idempotent), so a seed can be re-issued safely after the operator widens a
filter.
"""

from __future__ import annotations

import argparse
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.eval import review as review_store  # noqa: E402
from src.eval.db import connect  # noqa: E402
from src.eval.store import ensure_schema  # noqa: E402

# Column list for the run picker: enough for the operator to recognise the V4
# batch (rubric carries the contract type, scored_at orders the iterations).
_RUNS_SQL = """
SELECT e.id, e.rubric_name, e.scored_at, e.all_pass, e.n_criteria, e.n_passed,
       e.prompt_name, e.variant_label,
       length(coalesce(e.draft_text, '')) AS draft_len,
       count(r.id) AS results
FROM eval_runs e
LEFT JOIN eval_criteria_results r ON r.run_id = e.id
WHERE e.rubric_name ~ %s
GROUP BY e.id
ORDER BY e.scored_at DESC
LIMIT %s
"""


def _candidates(args) -> list[dict]:
    """Sampled eval_criteria_results rows, grouped-ready for stratification."""
    conn = connect()
    try:
        params: list = [args.rubric_regex]
        sql = [
            "SELECT r.id, r.criterion_id, e.id AS run_id, e.rubric_name, e.scored_at",
            "FROM eval_criteria_results r",
            "JOIN eval_runs e ON e.id = r.run_id",
            "WHERE e.rubric_name ~ %s",
        ]
        if args.run_ids:
            sql.append("AND e.id = ANY(%s)")
            params.append(args.run_ids)
        if args.types:
            # contract type lives in the rubric name (contract_<type>_v<N>)
            sql.append("AND e.rubric_name ~ ANY(%s)")
            params.extend([f"^contract_{t}_v[0-9]+$" for t in args.types])
        sql.append("ORDER BY e.scored_at, r.ordinal, r.id")
        rows = conn.execute("\n".join(sql), tuple(params)).fetchall()
    finally:
        conn.close()
    for row in rows:
        row["contract_type"] = review_store.contract_type_from_rubric(row["rubric_name"])
    return rows


def _list_runs(args) -> None:
    conn = connect()
    try:
        rows = conn.execute(_RUNS_SQL, (args.rubric_regex, args.list_runs)).fetchall()
    finally:
        conn.close()
    if not rows:
        print(f"no eval runs match rubric regex {args.rubric_regex!r}")
        return
    print(f"{'run_id':>7}  {'rubric':<28} {'scored_at':<26} {'pass':>4} {'n_pass':>6} "
          f"{'results':>7} {'draft':>6}  variant")
    for r in rows:
        print(f"{r['id']:>7}  {r['rubric_name']:<28} {str(r['scored_at']):<26} "
              f"{r['all_pass']:>4} {r['n_passed']:>3}/{r['n_criteria']:<2} "
              f"{r['results']:>7} {r['draft_len']:>6}  {r['variant_label'] or ''}")
    print(f"\n{len(rows)} run(s). Pin the ones you want with --run-ids.")


def _seed(args) -> None:
    rows = _candidates(args)
    if not rows:
        print("no eval_criteria_results match the filters — nothing to seed")
        return

    by_type: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_type[row["contract_type"] or "unknown"].append(row)

    rng = random.Random(args.seed)
    picked: list[dict] = []
    for ctype in sorted(by_type):
        pool = by_type[ctype]
        take = pool if args.per_type <= 0 else rng.sample(pool, min(args.per_type, len(pool)))
        picked.extend(take)
        print(f"  {ctype:<28} pool={len(pool):<5} picked={len(take)}")

    ensure_schema()
    out = review_store.create_batch(
        batch_id=args.batch_id,
        batch_type=args.batch_type,
        eval_criteria_result_ids=[r["id"] for r in picked],
        annotators=args.annotators,
    )
    print(
        f"\nbatch {out['batch_id']!r} ({out['batch_type']}): "
        f"created={out['created']} existing={out['existing']} total={out['total']}"
    )
    print("Open /review in the web workbench to annotate.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batch-id", help="batch identifier (required unless --list-runs)")
    ap.add_argument("--batch-type", choices=review_store.BATCH_TYPES, default="validity")
    ap.add_argument("--rubric-regex", default="^contract_",
                    help="regex over eval_runs.rubric_name (default: contract rubrics)")
    ap.add_argument("--types", nargs="*", help="contract type keys to include (e.g. lease sale)")
    ap.add_argument("--run-ids", type=lambda s: [int(x) for x in s.split(",") if x.strip()],
                    help="pin specific eval_runs ids, comma-separated")
    ap.add_argument("--per-type", type=int, default=3,
                    help="criteria results to sample per contract type (0 = all)")
    ap.add_argument("--annotators", type=int, default=2,
                    help="annotator slots per item (default 2, for kappa)")
    ap.add_argument("--seed", type=int, default=20260921, help="sampling seed (deterministic)")
    ap.add_argument("--list-runs", type=int, metavar="N",
                    help="list the newest N matching runs and exit")
    args = ap.parse_args()

    if args.list_runs:
        _list_runs(args)
        return
    if not args.batch_id:
        ap.error("--batch-id is required unless --list-runs is given")
    _seed(args)


if __name__ == "__main__":
    main()
