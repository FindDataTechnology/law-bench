"""Seed Category B generator-only types into the law-bench clauses table.

Idempotent: ``upsert_clause`` keys on ``(source_path, section, body_hash)`` so
re-runs update in place (or insert a new row only if the generator YAML body
drifted — Task 6 formalizes drift tracking).

Run from law-template root with database_url exported:
    database_url=postgresql://app:CHANGEME@localhost:15432/law_bench \
        python scripts/import_generator_types.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.clauses.generator_import import build_registry, import_type

# 23 Category B types (pawn excluded per design.md scope — 23, not 24).
CAT_B = [
    "mortgage", "pledge", "will", "prenup", "marital-property",
    "divorce", "adoption", "legacy-support", "elderly-support",
    "estate-division", "debt-transfer", "debt-restructuring",
    "settlement", "accident-settlement", "nda", "non-compete",
    "internship", "training", "labor-service", "housekeeping",
    "shareholders", "investment", "shop-transfer",
]


def main() -> None:
    reg, h = build_registry()
    print(f"source_hash={h} | seeding {len(CAT_B)} Category B types")
    total_written = 0
    for key in CAT_B:
        res = import_type(key, dry_run=False, registry=reg)
        total_written += res["written"]
        ids = res["ids"]
        tail = f"{ids[:3]}… (+{len(ids)-3})" if len(ids) > 3 else str(ids)
        print(f"  {key:<22} written={res['written']:>2} ids={tail}")
    print(f"done | {len(CAT_B)} types, {total_written} clauses written")


if __name__ == "__main__":
    main()
