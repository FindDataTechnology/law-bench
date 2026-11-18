#!/usr/bin/env python3
"""Register legal_topic dimension for all contract types based on rubric criteria.

This script extracts rubric criterion names and registers them as legal_topic
values for each contract type. This establishes the semantic bridge between
clauses and rubric criteria for the V4 self-iteration pipeline.

Usage:
    python scripts/register_legal_topic_dims.py
"""

import sys
from pathlib import Path

# Add repo root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()

from src.clauses.tags import register_legal_topic_dims, load_vocab_from_db, TAG_VOCAB
from src.eval.rubric import list_rubrics, load_criteria


def main() -> int:
    print("Loading vocab from DB...")
    load_vocab_from_db()

    print("\nFetching all rubrics...")
    rubrics = list_rubrics()

    # Group rubrics by contract type (latest version only)
    type_to_rubric = {}
    for r in rubrics:
        if r["source"] != "local":
            continue
        name = r["name"]
        # Extract contract type from rubric name (e.g., "contract_sale_v3" -> "sale")
        if not name.startswith("contract_"):
            continue
        parts = name.split("_")
        if len(parts) < 3:
            continue
        # Handle multi-word types (e.g., "real_estate_sale")
        contract_type = "_".join(parts[1:-1]) if parts[-1].startswith("v") else "_".join(parts[1:])

        # Keep latest version
        if contract_type not in type_to_rubric or name > type_to_rubric[contract_type]["name"]:
            type_to_rubric[contract_type] = r

    print(f"Found {len(type_to_rubric)} contract types with rubrics\n")

    # Register legal_topic for each type
    registered = 0
    for contract_type, rubric in sorted(type_to_rubric.items()):
        try:
            criteria = load_criteria(rubric["name"])
            criteria_names = [c["id"] for c in criteria]

            print(f"Registering {contract_type}: {len(criteria_names)} topics")
            print(f"  Topics: {', '.join(criteria_names[:5])}{'...' if len(criteria_names) > 5 else ''}")

            register_legal_topic_dims(contract_type, criteria_names, db=None)
            registered += 1
        except Exception as e:
            print(f"  ⚠ Error: {e}")

    print(f"\n✅ Registered legal_topic for {registered}/{len(type_to_rubric)} types")

    # Verify
    print("\nVerifying registration...")
    sale_vocab = TAG_VOCAB.get("sale", {})
    if "legal_topic" in sale_vocab:
        print(f"sale legal_topic: {len(sale_vocab['legal_topic'])} values")
        print(f"  Sample: {', '.join(sale_vocab['legal_topic'][:5])}")
    else:
        print("⚠ sale legal_topic not found in TAG_VOCAB")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
