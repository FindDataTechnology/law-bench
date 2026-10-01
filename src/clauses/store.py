"""Postgres CRUD for the ``clauses`` table (base / tagged / custom).

Reuses :func:`src.eval.db.connect` (the shared connection model - a request or
test can inject a borrowed connection) and :func:`src.eval.store.ensure_schema`
(so the table exists on first write). Idempotent upsert for base/tagged clauses
is keyed on ``(source_path, section, body_hash)`` via a partial unique index;
custom clauses (``source_path`` null) are plain inserts by id.

Dashboard-created/edited clauses carry ``manual=true`` so re-extraction
(:func:`delete_auto_clauses`) preserves them.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Optional

import psycopg
from psycopg.errors import DeadlockDetected, InFailedSqlTransaction
from psycopg.types.json import Jsonb

from src.eval.db import connect, close_shared_conn
from src.eval.errors import NotFoundError
from src.eval.store import ensure_schema

from .extract import _law_refs_from_body, _normalize_slot_instructions, section_rank
from .tags import FREE_FORM_TAGS, TAG_VOCAB, validate_tags

_INSERT_COLS = (
    "contract_type, section, body, slot_instructions, law_refs, "
    "source_path, source_doc_title, body_hash, created_at, updated_at, manual, tags, tag_review"
)


def _now() -> str:
    from src.eval.db import now_iso

    return now_iso()


def _row(clause: dict, *, now: str) -> tuple:
    # source lives in tags.source (base/tagged/custom). Bridge from legacy
    # `category` field if tags has no source. level is derived (not stored).
    # Body + slot_instruction names are normalized to canonical slots, and
    # body_hash is re-derived from the normalized body (keeps dedup consistent).
    from src.contracts.slot_ontology import normalize_body_slots, normalize_instruction_names

    ct = clause.get("contract_type")
    body = normalize_body_slots(clause["body"], ct)
    # Re-derive body_hash only when normalization changed the body; otherwise
    # honor a caller-provided hash (extraction sets md5(body); tests may set a
    # sentinel). This keeps dedup consistent for normalized bodies without
    # breaking callers that distinguish same-body rows via an explicit hash.
    if body != clause["body"]:
        body_hash = hashlib.md5(body.encode("utf-8")).hexdigest()
    else:
        body_hash = clause.get("body_hash") or hashlib.md5(body.encode("utf-8")).hexdigest()
    slot_instructions = _normalize_slot_instructions(
        body, normalize_instruction_names(clause.get("slot_instructions") or [], ct)
    )
    source_path = clause.get("source_path")
    tags = dict(clause.get("tags") or {})
    if "source" not in tags and "category" in clause:
        tags["source"] = clause["category"]
    source = tags.get("source")
    if source == "custom":
        source_path = None
    return (
        clause["contract_type"],
        clause["section"],
        body,
        Jsonb(slot_instructions),
        Jsonb(clause.get("law_refs") or []),
        source_path,
        clause.get("source_doc_title"),
        body_hash,
        now,
        now,
        bool(clause.get("manual", False)),
        Jsonb(validate_tags(tags, clause.get("contract_type"))),
        Jsonb(clause.get("tag_review") or {}),
    )


def _finalize(clause: dict, body: str) -> dict:
    """Re-derive ``body_hash``/``slot_instructions``/``law_refs`` from ``body``.

    ``body`` and ``slot_instructions`` are normalized to canonical slot names
    via :mod:`src.contracts.slot_ontology` (so the corpus stays name-consistent).
    ``slot_instructions`` keeps existing labels/descriptions for surviving slots
    and stubs any new ``{{slot}}``; ``law_refs`` is the ``《...》`` provisions.
    """
    from src.contracts.slot_ontology import normalize_body_slots, normalize_instruction_names

    ct = clause.get("contract_type")
    body = normalize_body_slots((body or "").strip(), ct)
    return {
        **clause,
        "body": body,
        "body_hash": hashlib.md5(body.encode("utf-8")).hexdigest(),
        "slot_instructions": _normalize_slot_instructions(
            body, normalize_instruction_names(clause.get("slot_instructions") or [], ct)
        ),
        "law_refs": _law_refs_from_body(body),
    }


def upsert_clause(clause: dict, db: Any = None) -> int:
    """Insert (or update on conflict) one clause; return its id.

    ``manual`` is taken from ``clause`` (false for auto-extracted). On conflict
    ``manual`` is left unchanged so a re-extract never un-marks a curated clause.
    """
    ensure_schema(db)
    now = _now()
    conn = connect(db)
    try:
        values = _row(clause, now=now)
        if clause.get("source_path") is not None:
            cur = conn.execute(
                "INSERT INTO clauses (" + _INSERT_COLS + ") VALUES "
                "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (source_path, section, body_hash) WHERE source_path IS NOT NULL "
                "DO UPDATE SET contract_type=EXCLUDED.contract_type, "
                "section=EXCLUDED.section, body=EXCLUDED.body, "
                "slot_instructions=EXCLUDED.slot_instructions, law_refs=EXCLUDED.law_refs, "
                "source_doc_title=EXCLUDED.source_doc_title, body_hash=EXCLUDED.body_hash, "
                "updated_at=EXCLUDED.updated_at RETURNING id",
                values,
            )
        else:
            cur = conn.execute(
                "INSERT INTO clauses (" + _INSERT_COLS + ") VALUES "
                "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                values,
            )
        conn.commit()
        return cur.fetchone()["id"]
    finally:
        conn.close()


def upsert_clauses(clauses: list[dict], db: Any = None) -> int:
    """Upsert many clauses in one connection; return the number written."""
    ensure_schema(db)
    if not clauses:
        return 0
    now = _now()
    conn = connect(db)
    try:
        for clause in clauses:
            values = _row(clause, now=now)
            if clause.get("source_path") is not None:
                conn.execute(
                    "INSERT INTO clauses (" + _INSERT_COLS + ") VALUES "
                    "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (source_path, section, body_hash) WHERE source_path IS NOT NULL "
                    "DO UPDATE SET contract_type=EXCLUDED.contract_type, "
                    "section=EXCLUDED.section, body=EXCLUDED.body, "
                    "slot_instructions=EXCLUDED.slot_instructions, law_refs=EXCLUDED.law_refs, "
                    "source_doc_title=EXCLUDED.source_doc_title, body_hash=EXCLUDED.body_hash, "
                    "updated_at=EXCLUDED.updated_at",
                    values,
                )
            else:
                conn.execute(
                    "INSERT INTO clauses (" + _INSERT_COLS + ") VALUES "
                    "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    values,
                )
        conn.commit()
        return len(clauses)
    finally:
        conn.close()


def create_clause(clause: dict, db: Any = None) -> int:
    """Create a dashboard clause (``manual=true``, no corpus source).

    ``slot_instructions``/``law_refs``/``body_hash`` are re-derived from
    ``body``. Category semantics are enforced via :func:`_row`; ``source_path``
    is forced to null (dashboard clauses have no corpus origin).
    """
    ensure_schema(db)
    rec = _finalize({**clause, "source_path": None, "manual": True}, clause.get("body", ""))
    now = _now()
    conn = connect(db)
    try:
        cur = conn.execute(
            "INSERT INTO clauses (" + _INSERT_COLS + ") VALUES "
            "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            _row(rec, now=now),
        )
        conn.commit()
        return cur.fetchone()["id"]
    finally:
        conn.close()


def update_clause(clause_id: int, fields: dict, db: Any = None) -> dict:
    """Update a clause by id; re-derive body-dependent fields; set ``manual=true``.

    ``fields`` may carry ``body``, ``section``, ``category``, ``tags``.
    Unspecified fields keep their existing value.
    Raises :class:`NotFoundError` for an unknown id. ``slot_instructions``/
    ``law_refs``/``body_hash`` are re-derived from the (possibly edited) body.
    """
    ensure_schema(db)
    conn = connect(db)
    try:
        r = conn.execute("SELECT * FROM clauses WHERE id = %s", (clause_id,)).fetchone()
        if r is None:
            raise NotFoundError(f"clause not found: {clause_id}")
        existing = _row_to_dict(r)
        body = (fields.get("body") if fields.get("body") is not None else existing["body"]).strip()
        category = fields.get("category") or existing["category"]
        section = fields.get("section") or existing["section"]
        slot_instructions = _normalize_slot_instructions(body, existing.get("slot_instructions") or [])
        law_refs = _law_refs_from_body(body)
        body_hash = hashlib.md5(body.encode("utf-8")).hexdigest()
        # enforce source semantics (custom -> no source_path)
        source_path = existing["source_path"]
        if category == "custom":
            source_path = None
        # tags: curatorial, not body-derived - replace when supplied, else preserve.
        tags = validate_tags(fields["tags"], existing["contract_type"]) if "tags" in fields else (existing.get("tags") or {})
        # bridge: derive tags.source from the legacy category field
        if "category" in fields:
            tags["source"] = fields["category"]
        elif "source" not in tags:
            cat = existing.get("category")
            if cat:
                tags["source"] = cat
        now = _now()
        conn.execute(
            "UPDATE clauses SET section=%s, body=%s, slot_instructions=%s, law_refs=%s, "
            "body_hash=%s, source_path=%s, tags=%s, "
            "manual=true, updated_at=%s WHERE id=%s",
            (section, body, Jsonb(slot_instructions), Jsonb(law_refs), body_hash,
             source_path, Jsonb(tags), now, clause_id),
        )
        conn.commit()
        r2 = conn.execute("SELECT * FROM clauses WHERE id = %s", (clause_id,)).fetchone()
        return _row_to_dict(r2)
    finally:
        conn.close()


def delete_clause(clause_id: int, db: Any = None) -> int:
    """Delete one clause by id; return the count (1). Raise :class:`NotFoundError` if missing."""
    ensure_schema(db)
    conn = connect(db)
    try:
        cur = conn.execute("DELETE FROM clauses WHERE id = %s", (clause_id,))
        conn.commit()
        if (cur.rowcount or 0) == 0:
            raise NotFoundError(f"clause not found: {clause_id}")
        return cur.rowcount
    finally:
        conn.close()


def delete_clauses(source_path: str, db: Any = None) -> int:
    """Delete every clause sourced from ``source_path``; return the count."""
    ensure_schema(db)
    conn = connect(db)
    try:
        cur = conn.execute(
            "DELETE FROM clauses WHERE source_path = %s", (source_path,)
        )
        conn.commit()
        return cur.rowcount or 0
    finally:
        conn.close()


def delete_auto_clauses(source_path: str, db: Any = None) -> int:
    """Delete auto-extracted clauses for ``source_path`` (``manual IS NOT TRUE``).

    Used by re-extraction so dashboard-curated (``manual=true``) clauses for the
    source survive a refresh.
    """
    ensure_schema(db)
    conn = connect(db)
    try:
        cur = conn.execute(
            "DELETE FROM clauses WHERE source_path = %s AND (manual IS NOT TRUE)",
            (source_path,),
        )
        conn.commit()
        return cur.rowcount or 0
    finally:
        conn.close()


def _row_to_dict(r) -> dict:
    return {
        "id": r["id"],
        "contract_type": r["contract_type"],
        "category": (r["tags"] or {}).get("source"),
        "level": {"base": "national", "tagged": "local"}.get((r["tags"] or {}).get("source")),
        "section": r["section"],
        "body": r["body"],
        "slot_instructions": r["slot_instructions"] or [],
        "law_refs": r["law_refs"] or [],
        "source_path": r["source_path"],
        "source_doc_title": r["source_doc_title"],
        "body_hash": r["body_hash"],
        "manual": r["manual"] if "manual" in r.keys() else False,
        "tags": (r["tags"] if "tags" in r.keys() else None) or {},
        "tag_review": (r["tag_review"] if "tag_review" in r.keys() else None) or {},
    }


def _retry_db(func, max_retries: int = 3, base_delay: float = 0.1):
    """Retry a database operation if it hits a deadlock or connection error."""
    for attempt in range(max_retries + 1):
        try:
            return func()
        except (DeadlockDetected, psycopg.errors.AdminShutdown, psycopg.errors.OperationalError, psycopg.errors.InFailedSqlTransaction) as e:
            if attempt == max_retries:
                raise
            try:
                close_shared_conn()
            except Exception:
                pass
            delay = base_delay * (2 ** attempt)
            time.sleep(delay)


def list_clauses(
    contract_type: Optional[str] = None,
    *,
    category: Optional[str] = None,
    q: Optional[str] = None,
    tags: Optional[dict] = None,
    db: Any = None,
) -> list[dict]:
    """Return clauses filtered by type/category/tags/body-text, in section order.

    ``contract_type`` null returns all types. ``q`` does a case-insensitive
    ``ILIKE`` over ``body`` and ``source_doc_title``. ``tags`` filters by
    ``tags->>'<dim>' = '<val>'`` for each dim (free-form dims accept any value).
    Ordered by ``section_rank`` then id.
    """
    ensure_schema(db)
    where = []
    params: list = []
    if contract_type is not None:
        where.append("contract_type = %s")
        params.append(contract_type)
    if category is not None:
        where.append("tags->>'source' = %s")
        params.append(category)
    if q:
        where.append("(body ILIKE %s OR source_doc_title ILIKE %s)")
        params.append(f"%{q}%")
        params.append(f"%{q}%")
    if tags:
        universal = TAG_VOCAB.get(None, {})
        type_specific = TAG_VOCAB.get(contract_type, {}) if contract_type else {}
        for dim, val in tags.items():
            # `scenario` is always filterable (core scenario axis) even before
            # load_vocab_from_db() registers it as a per-type dim.
            if dim == "scenario" or dim in FREE_FORM_TAGS or dim in universal or dim in type_specific:
                where.append("tags->>%s = %s")
                params.append(dim)
                params.append(str(val))
    sql = "SELECT * FROM clauses"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id"

    def _do_query():
        conn = connect(db)
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    rows = _retry_db(_do_query)
    out = [_row_to_dict(r) for r in rows]
    out.sort(key=lambda c: (section_rank(c["section"]), c["id"]))
    return out


def search_clauses(
    q: Optional[str] = None,
    *,
    contract_type: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[dict] = None,
    db: Any = None,
) -> list[dict]:
    """Free-text search across clause bodies/titles, composed with the filters."""
    return list_clauses(contract_type, category=category, q=q, tags=tags, db=db)


def get_custom_clause(clause_id: int, db: Any = None) -> Optional[dict]:
    """Return one clause by id (used for custom clauses); None if missing."""
    ensure_schema(db)
    conn = connect(db)
    try:
        r = conn.execute("SELECT * FROM clauses WHERE id = %s", (clause_id,)).fetchone()
    finally:
        conn.close()
    return _row_to_dict(r) if r else None


def list_extracted_source_paths(db: Any = None) -> list[str]:
    """Distinct ``source_path`` values already extracted (for resumable runs)."""
    ensure_schema(db)
    conn = connect(db)
    try:
        rows = conn.execute(
            "SELECT DISTINCT source_path FROM clauses WHERE source_path IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    return [r["source_path"] for r in rows]


def count_clauses(db: Any = None) -> dict:
    """Return ``{total, base, tagged, custom}`` counts (for the web overview)."""
    ensure_schema(db)
    conn = connect(db)
    try:
        rows = conn.execute(
            "SELECT tags->>'source' AS category, COUNT(*) AS n FROM clauses GROUP BY tags->>'source'"
        ).fetchall()
    finally:
        conn.close()
    by_cat = {r["category"]: r["n"] for r in rows}
    return {
        "total": sum(by_cat.values()),
        "base": by_cat.get("base", 0),
        "tagged": by_cat.get("tagged", 0),
        "custom": by_cat.get("custom", 0),
    }


def counts_by_type(db: Any = None) -> list[dict]:
    """Per ``contract_type`` counts broken down by category + distinct scenarios.

    Returns ``[{contract_type, base, tagged, custom, scenarios:[...]}]`` ordered
    by contract_type (``scenarios`` are the distinct ``tags.scenario`` values for
    tagged clauses). Used by the ``/clauses`` browse page.
    """
    ensure_schema(db)
    conn = connect(db)
    try:
        rows = conn.execute(
            "SELECT contract_type, tags->>'source' AS source, tags->>'scenario' AS scenario, COUNT(*) AS n "
            "FROM clauses GROUP BY contract_type, tags->>'source', tags->>'scenario' "
            "ORDER BY contract_type"
        ).fetchall()
    finally:
        conn.close()
    by_type: dict[str, dict] = {}
    for r in rows:
        entry = by_type.setdefault(
            r["contract_type"], {"contract_type": r["contract_type"], "base": 0, "tagged": 0, "custom": 0, "scenarios": set()}
        )
        entry[r["source"]] = entry.get(r["source"], 0) + r["n"]
        if r["source"] == "tagged" and r["scenario"]:
            entry["scenarios"].add(r["scenario"])
    return [
        {**e, "scenarios": sorted(e["scenarios"])} for e in by_type.values()
    ]
