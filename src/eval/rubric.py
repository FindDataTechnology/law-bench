"""Load a rubric + its criteria from the PostgreSQL DB and map to the
harvey-labs criterion shape the evaluator consumes.

The shared schema (created by scripts/extract_harbor_rules.py) stores criteria
with columns: name, description, guidance. harvey-labs criteria instead have
id / title / match_criteria. We map here (no schema change):

    id             <- name        stable identifier (e.g. party_identification)
    title          <- description human-readable statement of what is checked
    match_criteria <- guidance    the "PASS if ... / FAIL if ..." standard the
                                  judge evaluates against (== harvey-labs field)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.settings import DEFAULT_DB  # retained as the legacy default param value

from .db import connect


def list_rubrics(db_path: Any = DEFAULT_DB) -> list[dict]:
    """List all rubrics (name, context, source) - handy for `--list-rubrics`."""
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name, context, source FROM rubrics ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return [{"name": r["name"], "context": r["context"], "source": r["source"]} for r in rows]


def load_criteria(rubric_name: str, db_path: Any = DEFAULT_DB) -> list[dict]:
    """Load a rubric's criteria, mapped to {id, title, match_criteria}.

    Raises KeyError if the rubric name is unknown, ValueError if it has no
    criteria.
    """
    conn = connect(db_path)
    try:
        rubric = conn.execute(
            "SELECT id, name, context FROM rubrics WHERE name = %s",
            (rubric_name,),
        ).fetchone()
        if rubric is None:
            raise KeyError(f"Rubric not found: {rubric_name!r}")
        rows = conn.execute(
            "SELECT name, description, guidance FROM criteria "
            "WHERE rubric_id = %s ORDER BY ordinal",
            (rubric["id"],),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        raise ValueError(f"Rubric {rubric_name!r} has no criteria")

    return [
        {
            "id": r["name"],
            "title": r["description"],
            "match_criteria": r["guidance"],
        }
        for r in rows
    ]
