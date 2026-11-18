"""Tag review helpers: per-dim approve/reject + assembly-ready check.

A clause is "assembly-ready" when every dim in its ``tags`` has
``tag_review[dim] == "approved"``. Assembly uses only assembly-ready custom
clauses; base/tagged are the backbone (not gated).

Review supports two granularities (per the design):
- per-dim: :func:`review_tag` sets one dim's status.
- bulk: :func:`bulk_review` sets all of a clause's tag dims to one status.
"""

from __future__ import annotations

from typing import Any

from src.eval.db import connect
from src.eval.errors import NotFoundError
from src.eval.store import ensure_schema

_REVIEW_STATUSES = ("pending", "approved", "rejected")

# Keys with this prefix inside tags/tag_review are importer provenance
# (_imported_at, _source_hash, _note), never review dimensions. Gating and
# bulk writes must skip them, and they must survive bulk writes.
METADATA_PREFIX = "_"


def _review_dims(tags: dict | None) -> list[str]:
    """Genuine review dims from ``tags`` (metadata-prefixed keys excluded)."""
    return [k for k in (tags or {}) if not k.startswith(METADATA_PREFIX)]


def is_assembly_ready(clause: dict) -> bool:
    """True when every set tag dim has ``tag_review[dim] == 'approved'``.

    ``_``-prefixed keys are importer metadata, not review dims: they are
    skipped on the tags side and ignored on the review side.
    """
    review = clause.get("tag_review") or {}
    return all(review.get(dim) == "approved" for dim in _review_dims(clause.get("tags")))


def review_tag(clause_id: int, dim: str, status: str, db: Any = None) -> None:
    """Set ``tag_review[dim] = status`` for one clause (per-dim review)."""
    if status not in _REVIEW_STATUSES:
        raise ValueError(f"invalid status: {status!r}; use one of {_REVIEW_STATUSES}")
    if dim.startswith(METADATA_PREFIX):
        raise ValueError(f"metadata key {dim!r} is not a review dimension")
    ensure_schema(db)
    conn = connect(db)
    try:
        cur = conn.execute(
            "UPDATE clauses SET tag_review = tag_review || jsonb_build_object(%s::text, %s::text) WHERE id = %s",
            (dim, status, clause_id),
        )
        conn.commit()
        if (cur.rowcount or 0) == 0:
            raise NotFoundError(f"clause not found: {clause_id}")
    finally:
        if db is None:
            conn.close()


def bulk_review(clause_id: int, status: str, db: Any = None) -> None:
    """Set all of a clause's tag dims to ``status`` (bulk approve/reject).

    Merge-write: genuine dims are set to ``status``, everything else already
    in ``tag_review`` (e.g. importer ``_``-prefixed provenance keys) is kept.
    """
    if status not in _REVIEW_STATUSES:
        raise ValueError(f"invalid status: {status!r}; use one of {_REVIEW_STATUSES}")
    from psycopg.types.json import Jsonb

    ensure_schema(db)
    conn = connect(db)
    try:
        r = conn.execute(
            "SELECT tags, tag_review FROM clauses WHERE id = %s", (clause_id,)
        ).fetchone()
        if r is None:
            raise NotFoundError(f"clause not found: {clause_id}")
        new_review = dict(r["tag_review"] or {})
        for dim in _review_dims(r["tags"]):
            new_review[dim] = status
        conn.execute(
            "UPDATE clauses SET tag_review = %s WHERE id = %s",
            (Jsonb(new_review), clause_id),
        )
        conn.commit()
    finally:
        if db is None:
            conn.close()


def list_pending(clause_type: str | None = None, db: Any = None) -> list[dict]:
    """Return clauses that have at least one pending tag dim (for the review UI)."""
    ensure_schema(db)
    conn = connect(db)
    try:
        sql = (
            "SELECT * FROM clauses WHERE "
            "EXISTS (SELECT 1 FROM jsonb_each_text(tag_review) WHERE value = 'pending')"
        )
        params: list = []
        if clause_type:
            sql += " AND contract_type = %s"
            params.append(clause_type)
        sql += " ORDER BY id"
        rows = conn.execute(sql, params).fetchall()
    finally:
        if db is None:
            conn.close()
    from src.clauses.store import _row_to_dict

    return [_row_to_dict(r) for r in rows]
