#!/usr/bin/env python3
"""Resolve article-level citations ("民法典第1085条") across the clause corpus.

Parses every clause body for 条文级 citations (arabic or chinese numerals,
optional 款/项), resolves each via the law-catalog name ladder + law-api full
text, and batch-upserts law_catalog.clause_article_refs (idempotent, stale
rows pruned). Outcomes are distinct: resolved / unresolved_name /
fetch_failed / out_of_range.

Requires LAW_SEARCH_ENABLED=true and LAW_API_KEY (without them the pass
resolves nothing beyond unresolved_name — it refuses to run to avoid writing
a misleading all-failure snapshot).

Usage::

    python scripts/resolve_article_citations.py            # resolve + persist
    python scripts/resolve_article_citations.py --dry-run  # parse+resolve, no writes
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(override=True)

from src.law_api import client as law_api  # noqa: E402
from src.law_catalog import article as lc_article  # noqa: E402
from src.law_catalog.resolve import LawCatalogIndex  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="resolve only; do not write clause_article_refs")
    args = ap.parse_args()

    if not law_api.enabled():
        print("law-api is disabled (set LAW_SEARCH_ENABLED=true and LAW_API_KEY); "
              "article resolution needs statute full texts.", file=sys.stderr)
        return 2

    if not law_api.smoke():
        print("law-api smoke check failed; aborting the pass.", file=sys.stderr)
        return 2

    if args.dry_run:
        from src.eval.db import connect
        from src.law_catalog.resolve import LawCatalogIndex

        conn = connect()
        try:
            clauses = conn.execute(
                "SELECT id, contract_type, body FROM clauses ORDER BY id"
            ).fetchall()
        finally:
            conn.close()
        index = LawCatalogIndex(db=conn)
        outcomes: Counter = Counter()
        samples = []
        fetch_cache: dict = {}
        for c in clauses:
            for cite in lc_article.parse_citations(c["body"] or ""):
                res = lc_article.resolve_article(cite, index, fetch_cache=fetch_cache)
                outcomes[res["outcome"]] += 1
                if res["outcome"] == "resolved" and len(samples) < 5:
                    samples.append({
                        "clause_id": c["id"], "citation": cite.raw,
                        "law_id": res["law_id"],
                        "article": res["article_text"][:60],
                    })
        print(json.dumps({"dry_run": True, "outcomes": dict(outcomes),
                          "distinct_laws_fetched": len(fetch_cache),
                          "samples": samples}, ensure_ascii=False, indent=2))
        return 0

    stats = lc_article.resolve_all_article_citations()
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
