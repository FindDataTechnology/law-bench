"""Command-line tool: extract 法律法规, generate contract DOCX/PDF, and audit
contract 母版 for slot completeness.

Usage::

    python -m src.contracts <contract_type> [--format pdf|docx|both] [--out DIR]
    python -m src.contracts --all [--format pdf|docx|both] [--out DIR]
    python -m src.contracts audit [--type <key>] [--json] [--strict] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.eval.errors import NotFoundError

from .audit import (
    TAIL_ALLOWED_SLOTS,
    audit_all,
    audit_template,
    build_aggregate,
)
from .generator import generate_contract
from .templates import list_contract_types

DEFAULT_REPORT_PATH = "output/contract_slot_audit.json"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.contracts",
        description="Extract 法律法规 and generate contract DOCX/PDF per contract class.",
    )
    parser.add_argument("contract_type", nargs="?", help="contract class key (e.g. sale)")
    parser.add_argument(
        "--format", choices=("docx", "pdf", "both"), default="pdf",
        help="output format (default: pdf)",
    )
    parser.add_argument("--all", action="store_true", help="generate for every contract class")
    parser.add_argument("--out", default=None, help="output directory (default: output/contracts)")
    return parser


def _print_paths(result: dict) -> None:
    for p in (result["docx_path"], result["pdf_path"]):
        if p:
            print(p)


# --- audit subcommand ------------------------------------------------------- #


def _audit_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.contracts audit",
        description="Audit contract 母版 for slot completeness (甲方/乙方/时间/...).",
    )
    parser.add_argument("--type", default=None, help="audit a single contract class (default: all)")
    parser.add_argument("--json", action="store_true", help="emit the structured report as JSON on stdout")
    parser.add_argument("--strict", action="store_true", help="exit non-zero if any template is failing")
    parser.add_argument(
        "--out",
        default=None,
        help=f"write the JSON report to this path (default: {DEFAULT_REPORT_PATH})",
    )
    return parser


def _print_audit_table(templates, aggregate: dict, missing_templates: list[str]) -> None:
    print(f"{'key':<28} {'status':<6} {'coverage':<8} gaps (missing / body-proper tail-only)")
    print("-" * 72)
    for t in templates:
        body_tail = [f"{s}:tail" for s in t.tail_only if s not in TAIL_ALLOWED_SLOTS]
        gaps = ",".join([*t.missing, *body_tail])
        print(f"{t.key:<28} {t.status:<6} {t.coverage:<8.2f} {gaps}")
    print("-" * 72)
    print(
        f"total={aggregate['total']} passed={aggregate['passed']} failed={aggregate['failed']}"
    )
    if missing_templates:
        print(f"missing_templates (no 母版 in registry): {', '.join(missing_templates)}")


def _write_audit_report(path: str, templates, aggregate: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"templates": [t.to_dict() for t in templates], "aggregate": aggregate}
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote slot-audit report to {p}", file=sys.stderr)


def _audit_main(argv: list[str]) -> int:
    args = _audit_parser().parse_args(argv)

    if args.type:
        try:
            result = audit_template(args.type)
        except NotFoundError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        templates = [result]
        missing_templates: list[str] = []
    else:
        report = audit_all()
        templates = report.templates
        missing_templates = report.aggregate.get("missing_templates", [])

    aggregate = build_aggregate(templates)
    aggregate["missing_templates"] = missing_templates

    if args.json:
        payload = {"templates": [t.to_dict() for t in templates], "aggregate": aggregate}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_audit_table(templates, aggregate, missing_templates)

    # Write the report file when --out is given, or when --json is set (so a JSON
    # run always leaves a report on disk at the default path unless redirected).
    if args.out or args.json:
        _write_audit_report(args.out or DEFAULT_REPORT_PATH, templates, aggregate)

    failing = aggregate["failing_templates"]
    return 1 if (args.strict and failing) else 0


# --- entrypoint ------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)

    # `audit` is a distinct verb routed to its own parser; everything else is
    # the existing generation path (preserved unchanged).
    if raw and raw[0] == "audit":
        return _audit_main(raw[1:])

    parser = _build_parser()
    args = parser.parse_args(raw)

    if args.all:
        types = list_contract_types()
        if not types:
            print("no contract types found", file=sys.stderr)
            return 1
        failed = 0
        for ct in types:
            try:
                result = generate_contract(ct["key"], format=args.format, out_dir=args.out)
            except Exception as exc:  # noqa: BLE001 - report and continue
                print(f"error generating {ct['key']}: {exc}", file=sys.stderr)
                failed += 1
                continue
            _print_paths(result)
        return 1 if failed else 0

    if not args.contract_type:
        parser.error("contract_type is required (or use --all, or the `audit` subcommand)")

    try:
        result = generate_contract(args.contract_type, format=args.format, out_dir=args.out)
    except Exception as exc:  # noqa: BLE001 - surface any error (e.g. unknown type)
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print_paths(result)
    return 0
