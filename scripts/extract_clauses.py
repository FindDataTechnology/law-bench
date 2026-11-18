#!/usr/bin/env python3
"""Resumable corpus extraction: MinIO 示范文本 -> LLM clause extraction -> Postgres.

Thin wrapper over ``src.clauses.run_extraction``. Re-running skips documents
already in the DB (unless ``--force``); the extraction cache under
``src/clauses/data/_extracted/`` avoids re-calling the LLM after a DB wipe.

Usage::

    uv run python scripts/extract_clauses.py [--limit N] [--force] [--prefix contracts/]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.clauses.cli import run_extraction  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract clauses from the MinIO corpus into Postgres.")
    parser.add_argument("--limit", type=int, default=None, help="only extract the first N documents")
    parser.add_argument("--force", action="store_true", help="re-extract even if already in the DB")
    parser.add_argument("--prefix", default="contracts/", help="MinIO prefix (default: contracts/)")
    args = parser.parse_args()
    summary = run_extraction(limit=args.limit, force=args.force, prefix=args.prefix)
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
