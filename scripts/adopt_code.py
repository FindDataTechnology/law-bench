"""Adopt one code (and all its articles) into the legal ontology, with the pack imported.

Why the import matters: the kernel folds names with rules a *pack* registers, so a
process that never imported ``packs.legal`` folds nothing and writes keys like
``中华人民共和国$NAME`` instead of ``$NAME``. The web app imports the pack at its
edge (``src/web/routes/console.py``); a script has to do it itself.

Also repairs a batch written before that import (``--clean-legacy-prefix``):
those units are soft-deleted through the kernel, never by SQL, so the change
stays in ``authoring_events``.

Run inside the pod::

    python3 scripts/adopt_code.py --query $NAME --dry-run
    python3 scripts/adopt_code.py --query $NAME
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from packs.legal import entity_keys  # noqa: E402,F401  (registers the fold rules)
from src.bench import authoring, corpus_catalog  # noqa: E402

LEGACY_PREFIX = "中华人民共和国"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--domain", default="legal")
    ap.add_argument("--library", default="law-library")
    ap.add_argument("--source", default="statutes")
    ap.add_argument("--query", required=True, help="title fragment, e.g. 民法典")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-batches", type=int, default=12)
    ap.add_argument("--clean-legacy-prefix", action="store_true")
    args = ap.parse_args(argv)

    from src.eval.db import connect

    conn = connect()
    try:
        page = corpus_catalog.documents(
            conn, library_key=args.library, source_key=args.source,
            q=args.query, limit=5, domain_key=args.domain,
        )
        if not page["rows"]:
            print(f"no document matches {args.query!r}", file=sys.stderr)
            return 1
        if len(page["rows"]) > 1:
            print("several matches; picking the largest:")
            for row in page["rows"]:
                print("  ", row["id"], row["title"], row["chunks"])
        doc = page["rows"][0]
        print(f"document: {doc['id']} {doc['title']} ({doc['chunks']} chunks)")
        if args.dry_run:
            print("[dry-run] nothing written")
            return 0

        out = corpus_catalog.adopt_document(
            conn, domain_key=args.domain, library_key=args.library,
            source_key=args.source, doc_id=doc["id"], operator="adopt_code",
        )
        print(f"document unit: {out['key']} (created={out['created']})")

        total = 0
        for i in range(args.max_batches):
            batch = corpus_catalog.adopt_clauses(
                conn, domain_key=args.domain, library_key=args.library,
                source_key=args.source, doc_id=doc["id"], operator="adopt_code",
                law_key=out["key"],
            )
            total += batch["adopted"]
            print(f"  batch {i + 1}: adopted={batch['adopted']} remaining={batch['remaining']} "
                  f"reason={batch['reason']}")
            if not batch["adopted"]:
                break
        print(f"articles adopted: {total}")

        if args.clean_legacy_prefix:
            # A batch written before the pack was imported carries the unfolded
            # title as its parent. Retire exactly those: the document unit under
            # the full title, and every ``<full title>#第N条`` below it.
            legacy_parent = doc["title"]
            # Read the keys by prefix, not by scanning a capped entity list: the
            # batch being repaired is exactly the one that can exceed that cap.
            rows = conn.execute(
                "SELECT kind, external_key FROM knowledge_units "
                "WHERE namespace = %s AND (tags->>'deleted') IS NULL "
                "AND (external_key = %s OR external_key LIKE %s)",
                (args.domain, legacy_parent, legacy_parent.replace("%", r"\%") + "#%"),
            ).fetchall()
            stale = [{"kind": r["kind"], "external_key": r["external_key"]} for r in rows]
            print(f"legacy units to retire: {len(stale)}")
            for unit in stale[:5]:
                print("   e.g.", unit["kind"], unit["external_key"])
            for unit in stale:
                authoring.authoring_delete_unit(
                    conn, domain_key=args.domain, kind=unit["kind"],
                    external_key=unit["external_key"], operator="adopt_code",
                )
            print(f"retired: {len(stale)}")
        counts = conn.execute(
            "SELECT kind, COUNT(*) AS n FROM knowledge_units "
            "WHERE namespace = %s AND (tags->>'deleted') IS NULL GROUP BY kind ORDER BY kind",
            (args.domain,),
        ).fetchall()
        print("live units:", {r["kind"]: r["n"] for r in counts})
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
