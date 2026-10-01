"""CLI for the clause knowledge base.

``python -m src.clauses extract [--limit N] [--force]`` runs resumable corpus
extraction (MinIO -> parse -> LLM extract -> Postgres). ``python -m src.clauses
generate <type> [--scenario <业务场景>] [--custom <id,...>] [--stance pro_a|pro_b|balanced] [--format pdf|docx|both]``
assembles a contract from base + tagged + custom clauses. ``stats`` prints the
clause counts.
"""

from __future__ import annotations

import argparse
import sys

from .assemble import generate_contract_assembled
from .corpus import iter_unique_documents, read_document
from .extract import extract_document
from .store import count_clauses, delete_auto_clauses, list_extracted_source_paths, upsert_clauses


def run_extraction(
    *, limit: int | None = None, force: bool = False, prefix: str = "contracts/"
) -> dict:
    """Run resumable corpus extraction; return ``{done, skipped, failed, clauses}``.

    Skips ``source_path``s already in the DB unless ``force``. Per-doc failures
    are isolated (reported to stderr, non-fatal). Uses the extraction cache so
    re-runs after a DB wipe do not re-call the LLM.
    """
    docs = iter_unique_documents(prefix)
    if limit:
        docs = docs[:limit]
    done = skip = failed = clauses = 0
    already = set() if force else set(list_extracted_source_paths())
    for d in docs:
        if d.source_path in already:
            skip += 1
            print(f"[skip] {d.source_path}")
            continue
        try:
            doc = read_document(d.object_name)
            record = extract_document(doc)
            delete_auto_clauses(d.source_path)  # preserve manual/curated clauses
            upsert_clauses(record["clauses"])
            n = len(record["clauses"])
            clauses += n
            done += 1
            print(
                f"[ok]   {d.source_path}  type={record['contract_type']} "
                f"prov={record['province']} level={record['level']} clauses={n}"
            )
        except Exception as exc:  # noqa: BLE001 - isolate per-doc failures
            failed += 1
            print(f"[fail] {d.source_path}: {exc}", file=sys.stderr)
    summary = {"done": done, "skipped": skip, "failed": failed, "clauses": clauses}
    print(
        f"\nextraction: done={done} skipped={skip} failed={failed} clauses={clauses}"
    )
    return summary


def _parse_ids(s: str | None) -> list[int] | None:
    if not s:
        return None
    out: list[int] = []
    for part in s.split(","):
        part = part.strip()
        if part:
            out.append(int(part))
    return out or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.clauses",
        description="Clause knowledge base: extract clauses from the corpus and assemble contracts.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_extract = sub.add_parser("extract", help="run resumable corpus extraction")
    p_extract.add_argument("--limit", type=int, default=None, help="only extract the first N documents")
    p_extract.add_argument("--force", action="store_true", help="re-extract even if already in the DB")
    p_extract.add_argument("--prefix", default="contracts/", help="MinIO prefix (default: contracts/)")

    p_gen = sub.add_parser("generate", help="assemble a contract from clauses")
    p_gen.add_argument("contract_type", help="contract type key (e.g. property_service)")
    p_gen.add_argument("--scenario", default=None, help="scenario tag (业务场景) for tagged-clause selection (e.g. 农产品买卖)")
    p_gen.add_argument("--custom", default=None, help="comma-separated custom clause ids")
    p_gen.add_argument(
        "--stance",
        default=None,
        choices=("pro_a", "pro_b", "balanced"),
        help="filter custom clauses to this stance (利益倾向)",
    )
    p_gen.add_argument("--format", default="pdf", choices=("pdf", "docx", "both"))
    p_gen.add_argument("--out", default=None, help="output directory (default: output/contracts)")

    sub.add_parser("stats", help="print clause counts by category")

    p_retag = sub.add_parser(
        "retag-scenario", help="assign tags.scenario to existing tagged clauses via LLM (one-time)"
    )
    p_retag.add_argument("--contract-type", default=None, help="limit to one contract type")
    p_retag.add_argument("--limit", type=int, default=None, help="only classify N clauses (smoke)")

    args = parser.parse_args(argv)

    if args.cmd == "extract":
        run_extraction(limit=args.limit, force=args.force, prefix=args.prefix)
        return 0
    if args.cmd == "stats":
        print(count_clauses())
        return 0
    if args.cmd == "retag-scenario":
        from .retag_scenario import retag_scenarios

        print(retag_scenarios(args.contract_type, limit=args.limit))
        return 0
    if args.cmd == "generate":
        try:
            result = generate_contract_assembled(
                args.contract_type,
                scenario=args.scenario,
                custom_clause_ids=_parse_ids(args.custom),
                stance=args.stance,
                format=args.format,
                out_dir=args.out,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if result["docx_path"]:
            print(result["docx_path"])
        if result["pdf_path"]:
            print(result["pdf_path"])
        return 0
    return 1
