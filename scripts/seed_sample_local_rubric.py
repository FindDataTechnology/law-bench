#!/usr/bin/env python3
"""Seed a sample locally-authored contract rubric to validate the open schema.

Demonstrates that a local rubric (source = local, context = contract) coexists
with harbor's reference rubrics in the same tables. Re-running is idempotent,
and harbor re-extraction never touches local rows.

The target is the PostgreSQL database addressed by ``database_url``; the legacy
``--db`` flag is accepted but ignored (no longer a file path).

Run:
    uv run python scripts/seed_sample_local_rubric.py
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

# Reuse the shared schema + helpers so the schema has one source of truth.
from extract_harbor_rules import DEFAULT_DB, create_schema, print_summary, project_root

SAMPLE_RUBRIC = {
    "name": "contract_drafting_v1",
    "context": "contract",
    "description": (
        "Sample locally-authored rubric for evaluating Chinese legal contract "
        "drafts. Illustrative - extend with real criteria as needed."
    ),
    "criteria": [
        {
            "name": "party_identification",
            "description": "Are all parties clearly identified with full legal names and roles (甲方/乙方)?",
            "guidance": "PASS if every party is named with its full legal entity name and designated role; FAIL if any party is unnamed, ambiguous, or only referenced by a pronoun.",
        },
        {
            "name": "governing_law_present",
            "description": "Does the contract specify the governing law (e.g., 中华人民共和国法律)?",
            "guidance": "PASS if a governing-law clause names the applicable jurisdiction explicitly; FAIL if absent or only implied.",
        },
        {
            "name": "clause_completeness",
            "description": "Are mandatory clauses present (e.g., 违约责任, 争议解决, 合同期限)?",
            "guidance": "PASS if the standard mandatory clauses for the contract type are present; FAIL if any required clause is missing.",
        },
        {
            "name": "legal_citation_accuracy",
            "description": "Are 法条 citations correct and current (e.g., 民法典 article numbers)?",
            "guidance": "PASS if cited statutes exist and article numbers are accurate; FAIL if a citation is fabricated, repealed, or misnumbered.",
        },
    ],
}


def upsert_local_rubric(conn, rubric: dict, now_iso: str) -> int:
    """Upsert a local rubric by ``name`` (source = 'local'). Returns the rubric id.

    Replaces the rubric's criteria wholesale so re-seeding mirrors the seed data
    exactly (handles added/removed/renamed criteria).
    """
    row = conn.execute(
        "SELECT id FROM rubrics WHERE name = %s AND source = 'local'",
        (rubric["name"],),
    ).fetchone()
    if row:
        rubric_id = row["id"]
        conn.execute(
            "UPDATE rubrics SET context = %s, description = %s WHERE id = %s",
            (rubric["context"], rubric["description"], rubric_id),
        )
    else:
        cur = conn.execute(
            "INSERT INTO rubrics (name, context, source, source_path, description, created_at) "
            "VALUES (%s, %s, 'local', NULL, %s, %s) RETURNING id",
            (rubric["name"], rubric["context"], rubric["description"], now_iso),
        )
        rubric_id = cur.fetchone()["id"]
    conn.execute("DELETE FROM criteria WHERE rubric_id = %s", (rubric_id,))
    for i, c in enumerate(rubric["criteria"]):
        conn.execute(
            "INSERT INTO criteria (rubric_id, name, description, guidance, ordinal) "
            "VALUES (%s, %s, %s, %s, %s)",
            (rubric_id, c["name"], c["description"], c["guidance"], i),
        )
    return rubric_id


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--db", type=Path, default=project_root() / DEFAULT_DB,
        help="(legacy, ignored) target is the PostgreSQL database addressed by database_url.",
    )
    args = ap.parse_args()

    from src.eval.db import connect

    conn = connect()
    try:
        create_schema(conn)
        now_iso = datetime.now(timezone.utc).isoformat()
        rid = upsert_local_rubric(conn, SAMPLE_RUBRIC, now_iso)
        conn.commit()
        print(f"Seeded local rubric '{SAMPLE_RUBRIC['name']}' -> "
              f"{len(SAMPLE_RUBRIC['criteria'])} criteria (rubric_id={rid})")
        print_summary(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
