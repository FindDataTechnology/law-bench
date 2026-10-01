#!/usr/bin/env python3
"""Verify legal_topic coverage for contract types.

Checks that each rubric criterion (legal_topic) has at least one assembly-ready
clause covering it. Reports gaps where topics have zero coverage.

Usage:
    # Check sale coverage
    python scripts/verify_topic_coverage.py --contract-type sale

    # Check all types
    python scripts/verify_topic_coverage.py --all

    # JSON output (for CI)
    python scripts/verify_topic_coverage.py --contract-type sale --json
"""

import argparse
import json
import sys
from pathlib import Path

# Add repo root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()

from src.clauses.tags import load_vocab_from_db, TAG_VOCAB
from src.eval.rubric import load_criteria, list_rubrics


def verify_contract_coverage(contract_type: str) -> dict:
    """Verify legal_topic coverage for a contract type.

    Args:
        contract_type: The contract type key

    Returns:
        Dict with coverage stats and gaps
    """
    from src.clauses.store import list_clauses

    # Load rubric criteria
    try:
        rubrics = [r for r in list_rubrics() if r["name"].startswith(f"contract_{contract_type}_")]
        if not rubrics:
            return {"error": f"No rubric found for {contract_type}"}

        latest_rubric = max(rubrics, key=lambda r: r["name"])
        criteria = load_criteria(latest_rubric["name"])
        criteria_ids = [c["id"] for c in criteria]
    except Exception as e:
        return {"error": f"Error loading rubric: {e}"}

    # Load clauses
    try:
        clauses = list_clauses(contract_type=contract_type)
    except Exception as e:
        return {"error": f"Error loading clauses: {e}"}

    # Count coverage per topic
    coverage = {topic: 0 for topic in criteria_ids}
    for clause in clauses:
        tags = clause.get("tags", {})
        topic = tags.get("legal_topic")
        if topic and topic in coverage:
            # Check if clause is assembly-ready (has tag_review approved or is base/tagged)
            source = tags.get("source")
            tag_review = clause.get("tag_review", {})

            # Base and tagged clauses are always ready
            if source in ("base", "tagged"):
                coverage[topic] += 1
            # Custom clauses need approved tag_review
            elif source == "custom" and all(v == "approved" for v in tag_review.values()):
                coverage[topic] += 1

    # Find gaps
    gaps = [topic for topic, count in coverage.items() if count == 0]

    return {
        "contract_type": contract_type,
        "rubric": latest_rubric["name"],
        "n_criteria": len(criteria_ids),
        "coverage": coverage,
        "gaps": gaps,
        "n_gaps": len(gaps),
        "total_clauses": len(clauses),
        "tagged_clauses": sum(1 for c in clauses if c.get("tags", {}).get("legal_topic")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract-type", help="Contract type to check")
    parser.add_argument("--all", action="store_true", help="Check all contract types")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    if not args.contract_type and not args.all:
        parser.error("Either --contract-type or --all is required")

    # Load vocab from DB
    load_vocab_from_db()

    if args.all:
        # Get all contract types
        from src.contracts.templates import list_contract_types
        types = [t["key"] for t in list_contract_types()]

        results = []
        total_gaps = 0
        for contract_type in types:
            result = verify_contract_coverage(contract_type)
            results.append(result)
            if "gaps" in result:
                total_gaps += result["n_gaps"]

        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print(f"{'Contract Type':<30} {'Criteria':<10} {'Tagged':<10} {'Gaps':<10}")
            print("─" * 60)
            for r in results:
                if "error" in r:
                    print(f"{r['contract_type']:<30} ERROR: {r['error']}")
                else:
                    print(f"{r['contract_type']:<30} {r['n_criteria']:<10} {r['tagged_clauses']:<10} {r['n_gaps']:<10}")

            print(f"\nTotal gaps: {total_gaps}")

        # Exit with error if any gaps
        return 1 if total_gaps > 0 else 0
    else:
        result = verify_contract_coverage(args.contract_type)

        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if "error" in result:
                print(f"ERROR: {result['error']}")
                return 1

            print(f"Contract: {result['contract_type']}")
            print(f"Rubric: {result['rubric']}")
            print(f"Criteria: {result['n_criteria']}")
            print(f"Total clauses: {result['total_clauses']}")
            print(f"Tagged clauses: {result['tagged_clauses']}")
            print(f"\nCoverage by topic:")
            for topic, count in sorted(result["coverage"].items()):
                status = "✓" if count > 0 else "✗ GAP"
                print(f"  {topic:<40} {count:>5} {status}")

            if result["gaps"]:
                print(f"\n⚠ {result['n_gaps']} gaps found:")
                for gap in result["gaps"]:
                    print(f"  - {gap}")
                return 1
            else:
                print(f"\n✅ Full coverage!")
                return 0


if __name__ == "__main__":
    raise SystemExit(main())
