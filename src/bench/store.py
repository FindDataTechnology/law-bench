"""Domain-neutral knowledge-unit store.

A knowledge unit is the platform's generic corpus atom: a typed (``kind``)
piece of curated content with tags, opaque domain attributes (``attrs``), a
provenance tier, and an upsert identity of ``(kind, namespace, external_key)``.
The first kind shipped is the seed clause corpus of the flagship domain pack;
new kinds (entities, indicators, QA pairs, ...) onboard without kernel changes.

Storage notes:

- The DDL is idempotent (``CREATE TABLE IF NOT EXISTS``) and applied from
  ``src.eval.store.ensure_schema`` alongside the other schemas, so a fresh
  database bootstraps on first connect exactly like the legacy tables.
- ``external_key`` is the domain pack's native upsert key (for the seed-clause
  kind: a ``source_path/section/body_hash`` triple). The kernel never
  interprets it.
- ``attrs`` carries domain fields that used to be columns (the flagship pack
  maps its legacy columnar fields in and out); the kernel treats it as opaque
  JSONB.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

BENCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_units (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind          TEXT NOT NULL,
    namespace     TEXT NOT NULL DEFAULT 'default',
    external_key  TEXT NOT NULL,
    body          TEXT NOT NULL,
    tags          JSONB NOT NULL DEFAULT '{}'::jsonb,
    attrs         JSONB NOT NULL DEFAULT '{}'::jsonb,
    tier          TEXT NOT NULL DEFAULT 'raw'
                  CHECK (tier IN ('raw','bronze','silver','gold')),
    source_path   TEXT,
    provenance    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS knowledge_units_upsert_uk
    ON knowledge_units (kind, namespace, external_key);
CREATE INDEX IF NOT EXISTS knowledge_units_kind_idx
    ON knowledge_units (kind, tier);
"""

_UNIT_COLS = (
    "id, kind, namespace, external_key, body, tags, attrs, tier, "
    "source_path, provenance, created_at, updated_at"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decode_jsonb(val: Any) -> Any:
    if isinstance(val, (dict, list)) or val is None:
        return val
    return json.loads(val)


def _row_to_dict(row: Any) -> dict:
    # Callers may hand over dict-row connections (row_factory=dict_row, as in
    # the test suite) or plain tuple rows (default factory); support both.
    if isinstance(row, dict):
        return {
            "id": row["id"],
            "kind": row["kind"],
            "namespace": row["namespace"],
            "external_key": row["external_key"],
            "body": row["body"],
            "tags": _decode_jsonb(row["tags"]),
            "attrs": _decode_jsonb(row["attrs"]),
            "tier": row["tier"],
            "source_path": row["source_path"],
            "provenance": _decode_jsonb(row["provenance"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    return {
        "id": row[0],
        "kind": row[1],
        "namespace": row[2],
        "external_key": row[3],
        "body": row[4],
        "tags": _decode_jsonb(row[5]),
        "attrs": _decode_jsonb(row[6]),
        "tier": row[7],
        "source_path": row[8],
        "provenance": _decode_jsonb(row[9]),
        "created_at": row[10],
        "updated_at": row[11],
    }


def upsert_knowledge_unit(
    conn: Any,
    *,
    kind: str,
    external_key: str,
    body: str,
    namespace: str = "default",
    tags: Optional[dict] = None,
    attrs: Optional[dict] = None,
    tier: str = "raw",
    source_path: Optional[str] = None,
    provenance: Optional[dict] = None,
) -> dict:
    """Insert or update one knowledge unit; returns the stored row as a dict."""
    if not kind or not external_key:
        raise ValueError("kind and external_key are required")
    now = _now()
    cur = conn.execute(
        """
        INSERT INTO knowledge_units
            (kind, namespace, external_key, body, tags, attrs, tier,
             source_path, provenance, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (kind, namespace, external_key) DO UPDATE SET
            body = EXCLUDED.body,
            tags = EXCLUDED.tags,
            attrs = EXCLUDED.attrs,
            tier = EXCLUDED.tier,
            source_path = EXCLUDED.source_path,
            provenance = EXCLUDED.provenance,
            updated_at = EXCLUDED.updated_at
        RETURNING id, kind, namespace, external_key, body, tags, attrs, tier,
                  source_path, provenance, created_at, updated_at
        """,
        (
            kind,
            namespace,
            external_key,
            body,
            json.dumps(tags or {}),
            json.dumps(attrs or {}),
            tier,
            source_path,
            json.dumps(provenance or {}),
            now,
            now,
        ),
    )
    row = cur.fetchone()
    conn.commit()
    return _row_to_dict(row)


def get_knowledge_unit(
    conn: Any, *, kind: str, external_key: str, namespace: str = "default"
) -> Optional[dict]:
    cur = conn.execute(
        f"SELECT {_UNIT_COLS} FROM knowledge_units "
        "WHERE kind = %s AND namespace = %s AND external_key = %s",
        (kind, namespace, external_key),
    )
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def list_knowledge_units(
    conn: Any,
    *,
    kind: Optional[str] = None,
    namespace: Optional[str] = None,
    tier: Optional[str] = None,
    limit: int = 200,
) -> list[dict]:
    """List units, most recently updated first; filters are optional."""
    where, params = [], []
    if kind is not None:
        where.append("kind = %s")
        params.append(kind)
    if namespace is not None:
        where.append("namespace = %s")
        params.append(namespace)
    if tier is not None:
        where.append("tier = %s")
        params.append(tier)
    sql = f"SELECT {_UNIT_COLS} FROM knowledge_units"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC, id DESC LIMIT %s"
    params.append(limit)
    cur = conn.execute(sql, params)
    return [_row_to_dict(r) for r in cur.fetchall()]
