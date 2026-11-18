#!/usr/bin/env python3
"""Import the 法规库 catalog export into the law-bench ``law_catalog`` replica.

Input: the full catalog export from the 法规库 PostgreSQL
(``SELECT id,title,category,publish,expiry,status,src_db,content_status FROM laws``)
as .json (array) or .jsonl (one law per line). Full-replace semantics: a
successful import leaves exactly the exported rows (idempotent re-run).

Usage::

    python scripts/import_law_catalog.py --file laws_export.jsonl

    # also load the built-in alias seeds (简称/旧称 → 全称)
    python scripts/import_law_catalog.py --file laws_export.jsonl --seed-aliases

Transfer: download the export from the 法规库 side's RustFS bucket first (see
docs/law-catalog-runbook.md). The import itself needs no network.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(override=True)

from src.law_catalog import store  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True, help="catalog export path (.json or .jsonl)")
    ap.add_argument(
        "--seed-aliases",
        action="store_true",
        help="also load the built-in alias seeds (never overwrites curated rows)",
    )
    args = ap.parse_args()

    rows = store.load_export_file(args.file)
    result = store.import_catalog(rows)
    print(json.dumps(result, ensure_ascii=False))
    print(
        f"imported {result['imported']} laws (max_id={result['max_id']}) "
        f"into law_catalog.laws"
    )
    if args.seed_aliases:
        from src.law_catalog.alias_seed import seed

        added = seed()
        print(f"alias seeds: +{added} added (existing rows untouched)")
    snap = store.catalog_snapshot()
    print(
        f"snapshot: rows={snap['rows']} max_id={snap['max_id']} "
        f"imported_at={snap['imported_at']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
