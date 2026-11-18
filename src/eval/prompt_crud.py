"""CRUD for generation prompts (local-only; always editable, no harbor analog).

Prompts live in the same PostgreSQL database as rubrics (``prompts`` table,
created by scripts/extract_harbor_rules.py) but are always locally authored
(``source = 'local'``) and freely editable - there is no harbor analog and no
read-only guard.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from src.settings import DEFAULT_DB  # retained as the legacy default param value

from .db import connect, now_iso
from .errors import ConflictError, NotFoundError, ValidationError
from .rubric_crud import require_name


def _require_prompt_fields(
    name: Optional[str],
    contract_type: Optional[str],
    purpose: Optional[str],
    content: Optional[str],
) -> tuple[str, str, str, str]:
    name = require_name(name, "Prompt name")
    contract_type = (contract_type or "").strip()
    purpose = (purpose or "").strip()
    content = (content or "").strip()
    if not contract_type:
        raise ValidationError("Prompt contract_type must not be empty.")
    if not purpose:
        raise ValidationError("Prompt purpose must not be empty.")
    if not content:
        raise ValidationError("Prompt content must not be empty.")
    return name, contract_type, purpose, content


def _check_duplicate_prompt_name(
    conn, name: str, exclude_id: Optional[int] = None
) -> None:
    row = conn.execute("SELECT id FROM prompts WHERE name = %s", (name,)).fetchone()
    if row is not None and row["id"] != exclude_id:
        raise ConflictError(f"A prompt named {name!r} already exists.")


def _get_prompt(conn, prompt_id: int) -> dict:
    row = conn.execute(
        "SELECT id, name, contract_type, purpose, content, source, prompt_type, "
        "description, created_at FROM prompts WHERE id = %s",
        (prompt_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"Prompt not found: id={prompt_id}")
    return row


def _get_prompt_by_name(conn, name: str) -> Optional[dict]:
    return conn.execute(
        "SELECT id, name, contract_type, purpose, content, source, prompt_type, "
        "description, created_at FROM prompts WHERE name = %s",
        (name,),
    ).fetchone()


def _prompt_detail(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "contract_type": row["contract_type"],
        "purpose": row["purpose"],
        "content": row["content"],
        "source": row["source"],
        "prompt_type": row["prompt_type"],
        "description": row["description"],
        "created_at": row["created_at"],
    }


def list_prompts(db_path: Any = DEFAULT_DB) -> list[dict]:
    """All prompts (without the content body), for the listing view."""
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, name, contract_type, purpose, source, prompt_type, "
            "description, created_at FROM prompts ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_prompt(name: str, db_path: Any = DEFAULT_DB) -> dict:
    """A prompt's full record (incl. content), looked up by name."""
    conn = connect(db_path)
    try:
        row = _get_prompt_by_name(conn, name)
        if row is None:
            raise NotFoundError(f"Prompt not found: {name!r}")
        return _prompt_detail(row)
    finally:
        conn.close()


def get_prompt_by_id(prompt_id: int, db_path: Any = DEFAULT_DB) -> dict:
    """A prompt's full record (incl. content), looked up by id."""
    conn = connect(db_path)
    try:
        return _prompt_detail(_get_prompt(conn, prompt_id))
    finally:
        conn.close()


def create_prompt(
    name: str,
    contract_type: str,
    purpose: str,
    content: str,
    description: Optional[str] = None,
    prompt_type: Optional[str] = None,
    db_path: Any = DEFAULT_DB,
) -> dict:
    """Create a local prompt (``source = 'local'``). Returns the new record."""
    name, contract_type, purpose, content = _require_prompt_fields(
        name, contract_type, purpose, content
    )
    prompt_type = (prompt_type or "").strip() or None
    conn = connect(db_path)
    try:
        _check_duplicate_prompt_name(conn, name)
        cur = conn.execute(
            "INSERT INTO prompts (name, contract_type, purpose, content, source, "
            "prompt_type, description, created_at) "
            "VALUES (%s, %s, %s, %s, 'local', %s, %s, %s) RETURNING id",
            (name, contract_type, purpose, content, prompt_type, description, now_iso()),
        )
        pid = cur.fetchone()["id"]
        conn.commit()
    finally:
        conn.close()
    return get_prompt_by_id(pid, db_path=db_path)


def update_prompt(
    prompt_id: int,
    name: str,
    contract_type: str,
    purpose: str,
    content: str,
    description: Optional[str] = None,
    prompt_type: Optional[str] = None,
    db_path: Any = DEFAULT_DB,
) -> dict:
    """Update a prompt's name, contract_type, purpose, content, prompt_type, and description."""
    name, contract_type, purpose, content = _require_prompt_fields(
        name, contract_type, purpose, content
    )
    prompt_type = (prompt_type or "").strip() or None
    conn = connect(db_path)
    try:
        _get_prompt(conn, prompt_id)  # raises NotFoundError if missing
        _check_duplicate_prompt_name(conn, name, exclude_id=prompt_id)
        conn.execute(
            "UPDATE prompts SET name = %s, contract_type = %s, purpose = %s, "
            "content = %s, prompt_type = %s, description = %s WHERE id = %s",
            (name, contract_type, purpose, content, prompt_type, description, prompt_id),
        )
        conn.commit()
    finally:
        conn.close()
    return get_prompt_by_id(prompt_id, db_path=db_path)


def delete_prompt(prompt_id: int, db_path: Any = DEFAULT_DB) -> None:
    """Delete a prompt. No child table, so nothing cascades."""
    conn = connect(db_path)
    try:
        _get_prompt(conn, prompt_id)  # raises NotFoundError if missing
        conn.execute("DELETE FROM prompts WHERE id = %s", (prompt_id,))
        conn.commit()
    finally:
        conn.close()


__all__ = [
    "list_prompts",
    "get_prompt",
    "get_prompt_by_id",
    "create_prompt",
    "update_prompt",
    "delete_prompt",
]
