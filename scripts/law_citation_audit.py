#!/usr/bin/env python3
"""Run the clause law-citation audit over the law_catalog replica.

Default: resolve the whole clause corpus (law_catalog.clause_law_refs, idempotent
full re-run) and write the markdown report to docs/law_citation_audit_report.md.

Classification is by the cited law's catalog status only — 已废止/失效 = repealed,
已修改 = amended, unresolved/NULL/dirty = fallback. ``expiry`` (施行日期) is never
consulted.

Usage::

    python scripts/law_citation_audit.py                 # resolve + report
    python scripts/law_citation_audit.py --resolve-only  # refresh links only
    python scripts/law_citation_audit.py --report-only   # re-render from stored links
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(override=True)

from src.law_catalog import audit, resolve  # noqa: E402

DEFAULT_REPORT = Path(__file__).resolve().parents[1] / "docs" / "law_citation_audit_report.md"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--resolve-only", action="store_true", help="skip the report write")
    ap.add_argument("--report-only", action="store_true", help="skip the resolve pass")
    ap.add_argument(
        "--out", default=str(DEFAULT_REPORT), help="report path (default docs/law_citation_audit_report.md)"
    )
    args = ap.parse_args()

    if not args.report_only:
        stats = resolve.resolve_all_clauses()
        print(
            "resolve: "
            + json.dumps(
                {
                    "clauses": stats["clauses"],
                    "citations": stats["citations"],
                    "resolved": stats["resolved"],
                    "unresolved_distinct": len(stats["unresolved_names"]),
                },
                ensure_ascii=False,
            )
        )
    if args.resolve_only:
        return 0

    result = audit.collect_audit()
    md = audit.write_report(result, args.out)
    print(
        "audit: "
        + json.dumps(result["summary"], ensure_ascii=False)
        + f" total={result['total']}"
    )
    print(f"report: {args.out} ({len(md.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
