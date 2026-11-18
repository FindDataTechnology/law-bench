"""CRUD for evaluation rubrics and their criteria (local-authored).

Reads/writes the schema created by scripts/extract_harbor_rules.py
(`rubrics` / `criteria` tables in the PostgreSQL database addressed by
``database_url``). The read side reuses `src/eval/rubric.py`; this module adds
the write side for locally-authored rubrics (``source = 'local'``).

Invariants enforced here (mirroring the ``evaluation-rules`` spec):

- Harbor rubrics (``source LIKE 'harbor:%'``) are read-only. Every write
  function rejects them - harbor rubrics are refreshed only by re-running
  extraction, never edited in place.
- Criterion names are unique within a rubric (``UNIQUE(rubric_id, name)`` at the
  DB layer); we check up-front to raise a clear error before hitting the raw
  constraint.
- Deleting a rubric cascades to its criteria (FK ``ON DELETE CASCADE``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from src.settings import DEFAULT_DB  # retained as the legacy default param value

from .db import connect, is_harbor, now_iso, renumber_criteria
from .errors import (
    ConflictError,
    HarborReadOnlyError,
    NotFoundError,
    ValidationError,
)


# --------------------------------------------------------------------------- #
# Row helpers
# --------------------------------------------------------------------------- #


def _get_rubric(conn, rubric_id: int) -> dict:
    row = conn.execute(
        "SELECT id, name, context, source, source_path, description, created_at "
        "FROM rubrics WHERE id = %s",
        (rubric_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"Rubric not found: id={rubric_id}")
    return row


def _get_rubric_by_name(conn, name: str) -> Optional[dict]:
    return conn.execute(
        "SELECT id, name, context, source, source_path, description, created_at "
        "FROM rubrics WHERE name = %s",
        (name,),
    ).fetchone()


def _assert_local(conn, rubric_id: int) -> dict:
    """Return the rubric row, raising if it is a read-only harbor rubric."""
    row = _get_rubric(conn, rubric_id)
    if is_harbor(row["source"]):
        raise HarborReadOnlyError(
            f"Rubric {row['name']!r} is a harbor reference rubric "
            f"(source={row['source']}) and is read-only. Re-run harbor "
            f"extraction to refresh it instead of editing it."
        )
    return row


def _assert_criterion_local(conn, criterion_id: int) -> tuple[dict, dict]:
    """Return (criterion row, rubric row), raising if the rubric is harbor."""
    crow = conn.execute(
        "SELECT id, rubric_id, name, description, guidance, ordinal "
        "FROM criteria WHERE id = %s",
        (criterion_id,),
    ).fetchone()
    if crow is None:
        raise NotFoundError(f"Criterion not found: id={criterion_id}")
    rubric = _assert_local(conn, crow["rubric_id"])
    return crow, rubric


def require_name(name: Optional[str], label: str = "Name") -> str:
    """Strip and validate a non-empty name; raise ValidationError if blank.

    Shared by rubric and prompt validation, hence public.
    """
    name = (name or "").strip()
    if not name:
        raise ValidationError(f"{label} must not be empty.")
    return name


def _require_criteria_fields(
    name: Optional[str], description: Optional[str], guidance: Optional[str]
) -> tuple[str, str, str]:
    name = require_name(name, "Criterion name")
    description = (description or "").strip()
    guidance = (guidance or "").strip()
    if not description:
        raise ValidationError("Criterion description must not be empty.")
    if not guidance:
        raise ValidationError("Criterion guidance must not be empty.")
    return name, description, guidance


def _check_duplicate_local_name(
    conn, name: str, exclude_rubric_id: Optional[int] = None
) -> None:
    row = conn.execute(
        "SELECT id FROM rubrics WHERE name = %s AND source = 'local'",
        (name,),
    ).fetchone()
    if row is not None and row["id"] != exclude_rubric_id:
        raise ConflictError(f"A local rubric named {name!r} already exists.")


def _check_duplicate_criterion_name(
    conn, rubric_id: int, name: str, exclude_id: Optional[int] = None
) -> None:
    row = conn.execute(
        "SELECT id FROM criteria WHERE rubric_id = %s AND name = %s",
        (rubric_id, name),
    ).fetchone()
    if row is not None and row["id"] != exclude_id:
        raise ConflictError(
            f"A criterion named {name!r} already exists in this rubric."
        )


def _detail(conn, rubric_id: int) -> dict:
    row = _get_rubric(conn, rubric_id)
    crits = conn.execute(
        "SELECT id, name, description, guidance, ordinal FROM criteria "
        "WHERE rubric_id = %s ORDER BY ordinal, id",
        (rubric_id,),
    ).fetchall()
    return {
        "id": row["id"],
        "name": row["name"],
        "context": row["context"],
        "source": row["source"],
        "source_path": row["source_path"],
        "description": row["description"],
        "created_at": row["created_at"],
        "is_harbor": is_harbor(row["source"]),
        "criterion_count": len(crits),
        "criteria": [dict(c) for c in crits],
    }


# --------------------------------------------------------------------------- #
# Read helpers (UI / JSON API)
# --------------------------------------------------------------------------- #


def list_rubrics_with_counts(db_path: Any = DEFAULT_DB) -> list[dict]:
    """All rubrics with a derived criterion count, for the listing view."""
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT r.id, r.name, r.context, r.source, r.source_path, "
            "r.description, r.created_at, "
            "(SELECT COUNT(*) FROM criteria c WHERE c.rubric_id = r.id) "
            "AS criterion_count "
            "FROM rubrics r ORDER BY r.id"
        ).fetchall()
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "context": r["context"],
                "source": r["source"],
                "source_path": r["source_path"],
                "description": r["description"],
                "created_at": r["created_at"],
                "criterion_count": r["criterion_count"],
                "is_harbor": is_harbor(r["source"]),
            }
            for r in rows
        ]
    finally:
        conn.close()


def get_rubric_detail(name: str, db_path: Any = DEFAULT_DB) -> dict:
    """A rubric's metadata and ordered criteria, looked up by name."""
    conn = connect(db_path)
    try:
        row = _get_rubric_by_name(conn, name)
        if row is None:
            raise NotFoundError(f"Rubric not found: {name!r}")
        return _detail(conn, row["id"])
    finally:
        conn.close()


def get_rubric_by_id(rubric_id: int, db_path: Any = DEFAULT_DB) -> dict:
    """A rubric's metadata and ordered criteria, looked up by id."""
    conn = connect(db_path)
    try:
        return _detail(conn, rubric_id)
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Rubric writes (local only)
# --------------------------------------------------------------------------- #


def create_rubric(
    name: str,
    context: str,
    description: Optional[str] = None,
    criteria: Optional[list[dict[str, str]]] = None,
    db_path: Any = DEFAULT_DB,
) -> dict:
    """Create a local rubric (``source = 'local'``) with zero or more criteria.

    Each criterion dict is ``{name, description, guidance}``. All criteria are
    validated up-front so a bad one cannot leave a half-created rubric. Returns
    the new rubric detail.
    """
    name = require_name(name, "Rubric name")
    context = (context or "").strip()
    if not context:
        raise ValidationError("Rubric context must not be empty.")

    validated: list[tuple[str, str, str]] = []
    for c in criteria or []:
        validated.append(
            _require_criteria_fields(c.get("name"), c.get("description"), c.get("guidance"))
        )

    conn = connect(db_path)
    try:
        _check_duplicate_local_name(conn, name)
        cur = conn.execute(
            "INSERT INTO rubrics (name, context, source, source_path, description, "
            "created_at) VALUES (%s, %s, 'local', NULL, %s, %s) RETURNING id",
            (name, context, description, now_iso()),
        )
        rubric_id = cur.fetchone()["id"]
        for i, (cname, cdesc, cguid) in enumerate(validated):
            _check_duplicate_criterion_name(conn, rubric_id, cname)
            conn.execute(
                "INSERT INTO criteria (rubric_id, name, description, guidance, "
                "ordinal) VALUES (%s, %s, %s, %s, %s)",
                (rubric_id, cname, cdesc, cguid, i),
            )
        conn.commit()
    finally:
        conn.close()
    return get_rubric_by_id(rubric_id, db_path=db_path)


def update_rubric(
    rubric_id: int,
    name: str,
    context: str,
    description: Optional[str] = None,
    db_path: Any = DEFAULT_DB,
) -> dict:
    """Update a local rubric's name, context, and description (criteria untouched)."""
    name = require_name(name, "Rubric name")
    context = (context or "").strip()
    if not context:
        raise ValidationError("Rubric context must not be empty.")
    conn = connect(db_path)
    try:
        _assert_local(conn, rubric_id)
        _check_duplicate_local_name(conn, name, exclude_rubric_id=rubric_id)
        conn.execute(
            "UPDATE rubrics SET name = %s, context = %s, description = %s WHERE id = %s",
            (name, context, description, rubric_id),
        )
        conn.commit()
    finally:
        conn.close()
    return get_rubric_by_id(rubric_id, db_path=db_path)


def delete_rubric(rubric_id: int, db_path: Any = DEFAULT_DB) -> None:
    """Delete a local rubric; its criteria cascade via FK ON DELETE CASCADE."""
    conn = connect(db_path)
    try:
        _assert_local(conn, rubric_id)
        conn.execute("DELETE FROM rubrics WHERE id = %s", (rubric_id,))
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Criterion writes (local rubrics only)
# --------------------------------------------------------------------------- #


def add_criterion(
    rubric_id: int,
    name: str,
    description: str,
    guidance: str,
    db_path: Any = DEFAULT_DB,
) -> dict:
    """Append a criterion to a local rubric at the next ordinal."""
    name, description, guidance = _require_criteria_fields(name, description, guidance)
    conn = connect(db_path)
    try:
        _assert_local(conn, rubric_id)
        _check_duplicate_criterion_name(conn, rubric_id, name)
        next_ordinal = conn.execute(
            "SELECT COALESCE(MAX(ordinal), -1) + 1 AS n FROM criteria WHERE rubric_id = %s",
            (rubric_id,),
        ).fetchone()["n"]
        cur = conn.execute(
            "INSERT INTO criteria (rubric_id, name, description, guidance, ordinal) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (rubric_id, name, description, guidance, next_ordinal),
        )
        cid = cur.fetchone()["id"]
        conn.commit()
    finally:
        conn.close()
    return {
        "id": cid,
        "rubric_id": rubric_id,
        "name": name,
        "description": description,
        "guidance": guidance,
        "ordinal": next_ordinal,
    }


def update_criterion(
    criterion_id: int,
    name: str,
    description: str,
    guidance: str,
    db_path: Any = DEFAULT_DB,
) -> dict:
    """Update a criterion's name/description/guidance (ordinal untouched)."""
    name, description, guidance = _require_criteria_fields(name, description, guidance)
    conn = connect(db_path)
    try:
        crow, rubric = _assert_criterion_local(conn, criterion_id)
        _check_duplicate_criterion_name(conn, rubric["id"], name, exclude_id=criterion_id)
        conn.execute(
            "UPDATE criteria SET name = %s, description = %s, guidance = %s WHERE id = %s",
            (name, description, guidance, criterion_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "id": criterion_id,
        "rubric_id": rubric["id"],
        "name": name,
        "description": description,
        "guidance": guidance,
        "ordinal": crow["ordinal"],
    }


def delete_criterion(criterion_id: int, db_path: Any = DEFAULT_DB) -> None:
    """Delete a criterion from a local rubric and renumber the survivors."""
    conn = connect(db_path)
    try:
        _, rubric = _assert_criterion_local(conn, criterion_id)
        conn.execute("DELETE FROM criteria WHERE id = %s", (criterion_id,))
        renumber_criteria(conn, rubric["id"])
        conn.commit()
    finally:
        conn.close()


def reorder_criteria(
    rubric_id: int, ordered_criterion_ids: list[int], db_path: Any = DEFAULT_DB
) -> list[int]:
    """Reassign ``ordinal`` to match the given order.

    The list must contain exactly the rubric's current criterion ids, once each.
    """
    conn = connect(db_path)
    try:
        _assert_local(conn, rubric_id)
        existing = {
            r["id"]
            for r in conn.execute(
                "SELECT id FROM criteria WHERE rubric_id = %s", (rubric_id,)
            ).fetchall()
        }
        ids = list(ordered_criterion_ids)
        if set(ids) != existing or len(ids) != len(existing):
            raise ValidationError(
                "Reorder list must contain exactly the current criteria ids, "
                "once each."
            )
        for i, cid in enumerate(ids):
            conn.execute(
                "UPDATE criteria SET ordinal = %s WHERE id = %s AND rubric_id = %s",
                (i, cid, rubric_id),
            )
        conn.commit()
        return ids
    finally:
        conn.close()


__all__ = [
    "require_name",
    "list_rubrics_with_counts",
    "get_rubric_detail",
    "get_rubric_by_id",
    "create_rubric",
    "update_rubric",
    "delete_rubric",
    "add_criterion",
    "update_criterion",
    "delete_criterion",
    "reorder_criteria",
]
