#!/usr/bin/env python3
"""Reclassify ``unknown`` corpus docs after adding contract types.

Deletes each unknown doc's extraction cache and re-runs the LLM extraction
(use_cache=False) so the new types in ``contract_types.json`` are available to
the classifier. The old ``unknown`` clauses for each source are dropped
(``delete_auto_clauses``) and the re-classified clauses upserted. Idempotent.

Usage::
    uv run python scripts/reclassify_unknown.py [--workers 6]
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.clauses.corpus import iter_unique_documents, read_document  # noqa: E402
from src.clauses.extract import _cache_path, extract_document  # noqa: E402
from src.clauses.store import delete_auto_clauses, upsert_clauses  # noqa: E402
from src.eval.db import connect  # noqa: E402
from src.eval.store import ensure_schema  # noqa: E402


def _unknown_source_paths() -> list[str]:
    conn = connect(None)
    try:
        rows = conn.execute(
            "SELECT DISTINCT source_path FROM clauses "
            "WHERE contract_type='unknown' AND source_path IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    return [r["source_path"] for r in rows]


def _reclassify(sp: str, doc) -> tuple[str, bool, str, int]:
    cache = _cache_path(sp)
    if cache.is_file():
        cache.unlink()  # force the LLM to re-run with the new types
    try:
        d = read_document(doc.object_name)
        record = extract_document(d, use_cache=False)
        delete_auto_clauses(sp)  # drop the old `unknown` clauses for this source
        upsert_clauses(record["clauses"])
        return (sp, True, record["contract_type"], len(record["clauses"]))
    except Exception as exc:  # noqa: BLE001
        return (sp, False, str(exc), 0)


def main() -> int:
    ap = argparse.ArgumentParser(description="Reclassify unknown corpus docs with new contract types.")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    ensure_schema()
    sps = _unknown_source_paths()
    docs = {d.source_path: d for d in iter_unique_documents()}
    todo = [(sp, docs[sp]) for sp in sps if sp in docs]
    print(f"unknown docs: {len(sps)} | found in corpus: {len(todo)} | workers={args.workers}", flush=True)
    ok = fail = 0
    reclassed: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(_reclassify, sp, doc) for sp, doc in todo]
        for i, fut in enumerate(as_completed(futs), 1):
            sp, ok2, ct, n = fut.result()
            if ok2:
                ok += 1
                reclassed[ct] = reclassed.get(ct, 0) + 1
                print(f"[{i}/{len(todo)}] ok   {sp} -> {ct} ({n} clauses)", flush=True)
            else:
                fail += 1
                print(f"[{i}/{len(todo)}] FAIL {sp}: {ct}", file=sys.stderr, flush=True)
    print(f"\ndone={ok} failed={fail} | reclassified to: {reclassed}", flush=True)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
