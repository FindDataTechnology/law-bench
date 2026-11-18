"""Declare the document shape of a corpus source (idempotent data migration).

Run inside the law-bench pod::

    python3 scripts/declare_document_sources.py --dry-run
    python3 scripts/declare_document_sources.py

Why data and not code: which payload field holds a document id is a property of
**that store**, not of the kernel. ``ingest_rule.document`` is where a source
says it (next to the ``match`` rule that already says which slice it is), so a
second vertical with different field names is a row, not a code change.

Only sources listed here are touched; an unknown source is reported, never
created. Re-running is a no-op (the mapping is merged, not appended twice).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

#: Payload field names of the Qdrant law corpus. ``kind`` is the instrument
#: type (法律/行政法规/…); ``category`` already drives the source filter.
LAW_DOCUMENT = {
    "id": "law_id",
    "title": "title",
    "text": "chunk_text",
    "order": "chunk_no",
    "kind": "law_type",
    "status": "law_status",
    "publish": "publish",
    # What a document becomes in the ontology is declared here too: the kernel
    # has no opinion about a domain's vocabulary.
    "unit_kind": "law",
    "clause_kind": "clause",
}

#: Corpora where the document row lives in its own table, joined by a doc id.
#: ``table`` names it; ``doc_ref`` is the join column on the chunk side; ``where``
#: keeps one library's generic table from spilling another domain's documents.
TEXT_DOCUMENT = {
    "table": "corpus_documents",
    "id": "id",
    "title": "title",
    "text": "content",
    "status": "status",
    "doc_ref": "document_id",
    "unit_kind": "document",
}

#: (library_key, source_key) → mapping to merge into that source's ingest_rule.
DECLARATIONS = {
    ("law-library", "statutes"): LAW_DOCUMENT,
    ("law-library", "administrative"): LAW_DOCUMENT,
    ("law-library", "judicial"): LAW_DOCUMENT,
    ("law-library", "local"): LAW_DOCUMENT,
    ("law-library", "departmental"): LAW_DOCUMENT,
    ("law-library", "amendment"): LAW_DOCUMENT,
    # "unclassified" is crawl residue by label (重下载/新法速递/规范性文件) but the
    # payload is the same shape, and it is where newly issued instruments land
    # first — the source a curator most wants to browse.
    ("law-library", "unclassified"): LAW_DOCUMENT,
    ("text-library", "gov"): TEXT_DOCUMENT,
}

#: Extra `where` clauses so a shared document table reports one line's documents.
WHERE = {("text-library", "gov"): {"domain": "gov"}}


def merge(rule: dict, document: dict) -> dict:
    out = json.loads(json.dumps(rule or {}))
    out["document"] = json.loads(json.dumps(document))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    from src.bench import libraries
    from src.eval.db import connect

    conn = connect()
    changed = 0
    try:
        for (lib_key, src_key), document in DECLARATIONS.items():
            lib = libraries.get_library(conn, library_key=lib_key)
            if lib is None:
                print(f"SKIP {lib_key}: library not registered", file=sys.stderr)
                continue
            row = conn.execute(
                "SELECT source_key, ingest_rule FROM library_sources "
                "WHERE library_id = %s AND source_key = %s",
                (lib["id"], src_key),
            ).fetchone()
            if row is None:
                print(f"SKIP {lib_key}/{src_key}: source not registered", file=sys.stderr)
                continue
            rule = row["ingest_rule"] or {}
            if isinstance(rule, str):
                rule = json.loads(rule)
            extra_where = WHERE.get((lib_key, src_key))
            if extra_where:
                rule = {**rule, "where": {**(rule.get("where") or {}), **extra_where}}
            before = json.dumps(rule.get("document"), sort_keys=True)
            after = json.dumps(document, sort_keys=True)
            if before == after:
                print(f"ok   {lib_key}/{src_key}: already declared")
                continue
            merged = merge(rule, document)
            if args.dry_run:
                print(f"DRY  {lib_key}/{src_key}: document = {after}")
                changed += 1
                continue
            conn.execute(
                "UPDATE library_sources SET ingest_rule = %s::jsonb "
                "WHERE library_id = %s AND source_key = %s",
                (json.dumps(merged), lib["id"], src_key),
            )
            changed += 1
            print(f"set  {lib_key}/{src_key}: document = {after}")
        if not args.dry_run:
            conn.commit()
        print(f"{'would change' if args.dry_run else 'changed'}: {changed}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
