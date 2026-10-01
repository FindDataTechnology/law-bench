#!/usr/bin/env python3
"""Parallel corpus extraction: MinIO 示范文本 -> LLM clause extraction -> Postgres.

Multi-threaded version of ``python -m src.clauses extract``. The LLM call is
I/O-bound, so a thread pool gives near-linear speedup (one LLM call per doc,
~16 in flight). Resumable: skips ``source_path``s already in the DB unless
``--force``. Per-doc failures are isolated (reported to stderr, non-fatal) and
re-runnable (the extraction cache under ``src/clauses/data/_extracted/`` avoids
re-calling the LLM for docs that already succeeded).

Usage::
    uv run python scripts/extract_clauses_parallel.py [--workers 16] [--limit N] [--force]
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.clauses.corpus import iter_unique_documents, read_document  # noqa: E402
from src.clauses.extract import extract_document  # noqa: E402
from src.clauses.store import (  # noqa: E402
    delete_auto_clauses,
    list_extracted_source_paths,
    upsert_clauses,
)
from src.eval.store import ensure_schema  # noqa: E402


def _extract_one(d) -> tuple[str, bool, int, str | None]:
    """Extract one doc -> store. Returns (source_path, ok, n_clauses, error)."""
    try:
        doc = read_document(d.object_name)
        record = extract_document(doc)
        delete_auto_clauses(d.source_path)  # preserve manual/curated clauses
        upsert_clauses(record["clauses"])
        return (d.source_path, True, len(record["clauses"]), None)
    except Exception as exc:  # noqa: BLE001 - isolate per-doc failures
        return (d.source_path, False, 0, str(exc))


def main() -> int:
    ap = argparse.ArgumentParser(description="Parallel corpus clause extraction.")
    ap.add_argument("--workers", type=int, default=16, help="concurrent LLM extractions")
    ap.add_argument("--limit", type=int, default=None, help="only process the first N todo docs")
    ap.add_argument("--force", action="store_true", help="re-extract even if already in the DB")
    args = ap.parse_args()
    ensure_schema()
    docs = iter_unique_documents()
    already = set() if args.force else set(list_extracted_source_paths())
    todo = [d for d in docs if d.source_path not in already]
    if args.limit:
        todo = todo[: args.limit]
    print(
        f"corpus={len(docs)} already={len(already)} todo={len(todo)} workers={args.workers}",
        flush=True,
    )
    done = failed = clauses = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(_extract_one, d) for d in todo]
        for i, fut in enumerate(as_completed(futs), 1):
            sp, ok, n, err = fut.result()
            if ok:
                done += 1
                clauses += n
                print(f"[{i}/{len(todo)}] ok   {sp}  clauses={n} (total={clauses})", flush=True)
            else:
                failed += 1
                print(f"[{i}/{len(todo)}] FAIL {sp}: {err}", file=sys.stderr, flush=True)
    print(f"\ndone={done} failed={failed} clauses={clauses} (of {len(todo)} todo)", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
