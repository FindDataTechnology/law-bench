#!/usr/bin/env python3
"""Offline (zero-LLM) content detector over a clauses dump — thin CLI shell.

All rules live in :mod:`src.clauses.content_checks`; the dump format is the
psql COPY output documented there. See ``scripts/content_remediation.py`` for
the mutation counterpart.

Usage::

    python scripts/content_check_offline.py output/prod_dump_lb_clauses.jsonl.gz \
        --out output/content_check_report.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.clauses.content_checks import check, parse_dump  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dump", help="path to clauses.jsonl.gz or plain jsonl/csv")
    ap.add_argument("--out", default="output/content_check_report.json")
    ap.add_argument("--max-per-check", type=int, default=400,
                    help="cap findings listed per check in the JSON")
    args = ap.parse_args()

    clauses = parse_dump(Path(args.dump))
    report = check(clauses)

    out = {
        "census": {
            "total": report["census"]["total"],
            "parse_errors": report["census"]["parse_errors"],
            "by_source": dict(report["census"]["by_source"]),
            "by_type": dict(sorted(report["census"]["by_type"].items())),
            "tag_review_status": dict(report["census"]["tag_review_status"]),
            "assembly_ready_custom": report["census"]["assembly_ready_custom"],
            "with_scenario_tag": report["census"]["with_scenario_tag"],
            "with_stance_tag": report["census"]["with_stance_tag"],
        },
        "findings": {
            name: {"count": len(items), "items": items[: args.max_per_check]}
            for name, items in sorted(report["findings"].items())
        },
    }

    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"clauses parsed: {out['census']['total']} "
          f"(parse_errors={out['census']['parse_errors']})")
    for name, info in out["findings"].items():
        print(f"  {name}: {info['count']}")
    print(f"report -> {outp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
