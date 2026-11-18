#!/usr/bin/env python3
"""Backfill ``eval_runs.outcome`` for rows written before the verdict ledger.

add-eval-verdict-ledger task 1.3. History rows have no ledger identity (no
subject / ruler / gate) and must NOT get one — inventing an identity for a run
that never had it would make two unlike things look comparable. All this script
does is derive the one field that IS derivable from what the row already says:

    all_pass = 1  →  outcome = 'pass'
    all_pass = 0  →  outcome = 'fail'

``inconclusive`` is deliberately never back-filled: it is a NEW semantic (the
evaluation could not decide), and no historical row can be assumed to mean that
just because it failed.

Idempotent: only rows whose ``outcome IS NULL`` are touched, so re-running is a
no-op and a second run cannot rewrite a meaning assigned by a real writer.

Usage:
    python scripts/backfill_verdict_outcomes.py [--dry-run]
Env: database_url (same DSN every other script reads)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report counts, change nothing")
    args = ap.parse_args(argv)

    dsn = os.environ.get("database_url") or os.environ.get("DATABASE_URL")
    if not dsn:
        print("error: database_url is not set", file=sys.stderr)
        return 2

    import psycopg
    from psycopg.rows import dict_row

    # ensure_schema first: it is what adds the ``outcome`` column (and creates the
    # tables on a fresh DB). Without it this script would fail on any database
    # that has not yet served a request since the deploy.
    from src.eval.store import ensure_schema

    ensure_schema(dsn)

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        counts = conn.execute(
            "SELECT all_pass, COUNT(*) AS n FROM eval_runs "
            "WHERE outcome IS NULL GROUP BY all_pass ORDER BY all_pass"
        ).fetchall()
        report = {("pass" if bool(r["all_pass"]) else "fail"): r["n"] for r in counts}
        print(f"rows needing an outcome: {report or 'none'}")
        if args.dry_run:
            print("dry run: nothing written")
            return 0
        if not report:
            print("already backfilled")
            return 0
        # One UPDATE, derived in SQL so the two paths cannot disagree about what
        # "all_pass=1 means pass" — the same rule store_result applies at write
        # time. ``all_pass`` is INTEGER (0/1), not boolean, since the table's
        # first release.
        cur = conn.execute(
            "UPDATE eval_runs "
            "SET outcome = CASE WHEN all_pass = 1 THEN 'pass' ELSE 'fail' END "
            "WHERE outcome IS NULL"
        )
        conn.commit()
        print(f"updated {cur.rowcount} row(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
