"""Postgres CRUD for the ``law_catalog`` schema (法规目录只读副本).

Tables (own schema, mirrors the external 法规库 catalog):

  law_catalog.laws             - the replica: id/title/category/publish/expiry/
                                 status/src_db/content_status. Full-replace
                                 import (idempotent re-run).
  law_catalog.aliases          - curated 简称/旧称 → catalog law. ``alias`` is
                                 stored post-normalization; ``source`` is
                                 manual | seed | review | non_match (a
                                 deliberate non-match hides the name from the
                                 review queue but never fabricates a link).
  law_catalog.clause_law_refs  - resolution results per clause × cited name:
                                 law_id, status snapshot, resolved_via.
                                 Independently re-runnable; NEVER writes to
                                 ``clauses.law_refs`` (a derived column).

``expiry`` (施行日期, not an expiry date) is stored verbatim for fidelity with
the source catalog but no reader in this package uses it for judgments.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import psycopg

from src.eval.db import connect, now_iso

_SCHEMA_DDL = """
CREATE SCHEMA IF NOT EXISTS law_catalog;

CREATE TABLE IF NOT EXISTS law_catalog.laws (
    id             BIGINT PRIMARY KEY,
    title          TEXT NOT NULL,
    category       TEXT,
    publish        TEXT,
    expiry         TEXT,
    status         TEXT,
    src_db         TEXT,
    content_status TEXT,
    imported_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS law_catalog.aliases (
    alias        TEXT PRIMARY KEY,
    law_id       BIGINT,
    target_title TEXT,
    source       TEXT NOT NULL DEFAULT 'manual',
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS law_catalog.clause_law_refs (
    clause_id    BIGINT NOT NULL,
    cited_name   TEXT NOT NULL,
    law_id       BIGINT,
    status       TEXT,
    resolved_via TEXT NOT NULL,
    resolved_at  TEXT NOT NULL,
    PRIMARY KEY (clause_id, cited_name)
);

CREATE TABLE IF NOT EXISTS law_catalog.clause_article_refs (
    clause_id       BIGINT NOT NULL,
    contract_type   TEXT,
    citation        TEXT NOT NULL,
    article_ordinal INT NOT NULL,
    law_id          BIGINT,
    article_text    TEXT,
    law_status      TEXT,
    outcome         TEXT NOT NULL,
    resolved_at     TEXT NOT NULL,
    PRIMARY KEY (clause_id, citation, article_ordinal)
);

CREATE TABLE IF NOT EXISTS law_catalog.successor_map (
    dead_law_id    BIGINT PRIMARY KEY,
    successor_law_id BIGINT,
    authority_law_id BIGINT,
    effective_date TEXT,
    rule_version   TEXT NOT NULL,
    needs_human    BOOLEAN NOT NULL DEFAULT false,
    seeded_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS law_catalog.citation_revisions (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    clause_id       BIGINT NOT NULL,
    contract_type   TEXT,
    batch           TEXT NOT NULL,
    cited_before    TEXT NOT NULL,
    cited_after     TEXT,
    dead_law_id     BIGINT,
    successor_law_id BIGINT,
    authority_law_id BIGINT,
    disposition     TEXT NOT NULL CHECK (disposition IN
                      ('applied','skipped-review','reviewed-no-action','rolled-back')),
    rule_version    TEXT,
    git_sha         TEXT,
    applied_at      TEXT NOT NULL,
    UNIQUE (clause_id, batch, cited_before)
);
"""

# Best-effort trigram support: the GIN index accelerates (and pg_trgm provides)
# similarity(). Without the extension the resolver's trigram rung degrades to
# "unresolved" (everything lands in the review queue) — see resolve.py.
_TRGM_DDL = (
    "CREATE EXTENSION IF NOT EXISTS pg_trgm; "
    "CREATE INDEX IF NOT EXISTS law_catalog_laws_title_trgm "
    "ON law_catalog.laws USING gin (title gin_trgm_ops);"
)

_EXPORT_FIELDS = (
    "id",
    "title",
    "category",
    "publish",
    "expiry",
    "status",
    "src_db",
    "content_status",
)


def ensure_schema(db=None) -> None:
    """Create the schema + tables idempotently; best-effort pg_trgm setup.

    The trigram extension may require one-time admin rights (see
    docs/law-catalog-runbook.md); a failure there is not fatal — the rest of
    the schema is still created and trgm matching degrades to the review queue.
    """
    conn = connect(db)
    try:
        conn.execute(_SCHEMA_DDL)
        try:
            conn.execute(_TRGM_DDL)
        except psycopg.errors.InsufficientPrivilege:
            conn.rollback()
        conn.commit()
    finally:
        conn.close()


def has_trgm(db=None) -> bool:
    """True when pg_trgm is installed (similarity() usable)."""
    conn = connect(db)
    try:
        row = conn.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') AS ok"
        ).fetchone()
        return bool(row["ok"])
    finally:
        conn.close()


def _validate_row(item: Any) -> dict:
    """Normalize one export row to the ``_EXPORT_FIELDS`` shape; loud on garbage."""
    if not isinstance(item, dict):
        raise ValueError(f"export row is not an object: {item!r}")
    law_id = item.get("id")
    title = (item.get("title") or "").strip()
    if law_id is None or not title:
        raise ValueError(f"export row missing id/title: {item!r}")
    row = {k: item.get(k) for k in _EXPORT_FIELDS}
    row["id"] = int(law_id)  # reject fractional ids loudly, keep BIGINT
    row["title"] = title
    return row


def load_export_file(path: str) -> list[dict]:
    """Read a catalog export (.json array or .jsonl, one law per line).

    Rows are validated (id + title required, id integer-like) and normalized to
    the ``_EXPORT_FIELDS`` key order. Extra keys from the export are dropped.
    """
    with open(path, "r", encoding="utf-8") as f:
        head = f.read(1)
        f.seek(0)
        if head == "[":
            raw = json.load(f)
        else:
            raw = [json.loads(line) for line in f if line.strip()]

    rows = [_validate_row(item) for item in raw]
    if len({r["id"] for r in rows}) != len(rows):
        raise ValueError("export contains duplicate law ids")
    return rows


def import_catalog(rows: list[dict], db=None) -> dict:
    """Full-replace import of the catalog replica (idempotent re-run).

    Truncate-then-insert inside one transaction: a failed import leaves the
    previous replica untouched; a successful one leaves exactly ``rows``.
    Resolution results are NOT cleared - they are refreshed by the resolve
    pass and keep pointing at stable law ids across refreshes.
    """
    if not rows:
        raise ValueError("refusing to import an empty catalog (probable bad export)")
    rows = [_validate_row(r) for r in rows]
    conn = connect(db)
    try:
        ensure_schema(conn)
        now = now_iso()
        with conn.transaction():
            conn.execute("TRUNCATE law_catalog.laws")
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO law_catalog.laws "
                    "(id, title, category, publish, expiry, status, src_db, content_status, imported_at) "
                    "VALUES (%(id)s, %(title)s, %(category)s, %(publish)s, %(expiry)s, "
                    "%(status)s, %(src_db)s, %(content_status)s, %(imported_at)s)",
                    [{**r, "imported_at": now} for r in rows],
                )
        conn.commit()
        return {"imported": len(rows), "max_id": max(r["id"] for r in rows)}
    finally:
        conn.close()


def catalog_snapshot(db=None) -> dict:
    """Identity line for reports: row count, max id, last import time."""
    conn = connect(db)
    try:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT count(*) AS n, coalesce(max(id), 0) AS max_id, "
            "coalesce(max(imported_at), '') AS imported_at FROM law_catalog.laws"
        ).fetchone()
        return {
            "rows": int(row["n"]),
            "max_id": int(row["max_id"]),
            "imported_at": row["imported_at"],
        }
    finally:
        conn.close()


def get_law(law_id: int, db=None) -> Optional[dict]:
    """One replica row by id, or None."""
    conn = connect(db)
    try:
        return conn.execute(
            "SELECT id, title, category, publish, expiry, status, src_db, content_status "
            "FROM law_catalog.laws WHERE id = %s",
            (law_id,),
        ).fetchone()
    finally:
        conn.close()


# --- aliases -----------------------------------------------------------------


def upsert_alias(
    alias: str,
    target_title: Optional[str],
    law_id: Optional[int],
    source: str = "manual",
    db=None,
) -> None:
    """Insert/refresh one alias row (``alias`` stored post-normalization).

    ``source='non_match'`` records a deliberate non-match (``law_id`` and
    ``target_title`` both NULL); it suppresses the name in the review queue
    without fabricating a link.
    """
    from .resolve import normalize_name

    norm = normalize_name(alias)
    if not norm:
        raise ValueError("alias normalizes to empty")
    if source == "non_match":
        target_title = law_id = None
    elif not target_title and law_id is None:
        raise ValueError("alias needs a target title or law_id")
    conn = connect(db)
    try:
        ensure_schema(conn)
        conn.execute(
            "INSERT INTO law_catalog.aliases (alias, law_id, target_title, source, created_at) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (alias) DO UPDATE SET "
            "law_id = EXCLUDED.law_id, target_title = EXCLUDED.target_title, "
            "source = EXCLUDED.source",
            (norm, law_id, target_title, source, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def list_aliases(db=None) -> dict[str, dict]:
    """All alias rows keyed by normalized alias."""
    conn = connect(db)
    try:
        rows = conn.execute(
            "SELECT alias, law_id, target_title, source FROM law_catalog.aliases"
        ).fetchall()
        return {r["alias"]: dict(r) for r in rows}
    finally:
        conn.close()


def seed_aliases(mapping: dict[str, str], source: str = "seed", db=None) -> int:
    """Insert alias → full-title seeds that are not present yet; returns added count.

    Existing rows (any source) are never overwritten - curation wins over seed.
    """
    from .resolve import normalize_name

    conn = connect(db)
    try:
        ensure_schema(conn)
        existing = {r["alias"] for r in conn.execute(
            "SELECT alias FROM law_catalog.aliases"
        ).fetchall()}
        added = 0
        for alias, title in mapping.items():
            norm = normalize_name(alias)
            if not norm or norm in existing:
                continue
            conn.execute(
                "INSERT INTO law_catalog.aliases (alias, law_id, target_title, source, created_at) "
                "VALUES (%s, NULL, %s, %s, %s)",
                (norm, title.strip(), source, now_iso()),
            )
            existing.add(norm)
            added += 1
        conn.commit()
        return added
    finally:
        conn.close()


# --- clause_law_refs (resolution results) ------------------------------------


def list_resolutions(db=None) -> list[dict]:
    """All resolution results joined with clause context + replica row.

    LEFT JOINs so unresolved citations and replica misses still come back.
    """
    conn = connect(db)
    try:
        return conn.execute(
            "SELECT r.clause_id, r.cited_name, r.law_id, r.status AS law_status, "
            "r.resolved_via, r.resolved_at, "
            "c.contract_type, c.section, l.title, l.category, "
            "l.status AS catalog_status "
            "FROM law_catalog.clause_law_refs r "
            "LEFT JOIN clauses c ON c.id = r.clause_id "
            "LEFT JOIN law_catalog.laws l ON l.id = r.law_id "
            "ORDER BY c.contract_type, r.clause_id, r.cited_name"
        ).fetchall()
    finally:
        conn.close()


def distinct_unresolved(db=None) -> list[dict]:
    """Distinct unresolved cited names with occurrence counts.

    Deliberate non-matches (aliases.source='non_match') are excluded - an
    operator already looked at them. Aliases are stored post-normalization
    (stripped 中华人民共和国 prefix / 《》), so the comparison tries both the
    raw cited name and its prefix-stripped form - otherwise "中华人民共和国X"
    citations would stay in the queue after marking "X".
    """
    conn = connect(db)
    try:
        return conn.execute(
            "SELECT r.cited_name, count(*) AS occurrences "
            "FROM law_catalog.clause_law_refs r "
            "WHERE r.resolved_via = 'unresolved' "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM law_catalog.aliases a "
            "  WHERE a.source = 'non_match' "
            "  AND (a.alias = r.cited_name "
            "       OR a.alias = regexp_replace(r.cited_name, '^《?中华人民共和国', ''))) "
            "GROUP BY r.cited_name ORDER BY occurrences DESC, r.cited_name"
        ).fetchall()
    finally:
        conn.close()


def suggest_candidates(name: str, limit: int = 3, db=None) -> list[dict]:
    """Top trigram candidates for an unresolved name (review-queue hints).

    Uses a floor below the resolve threshold: suggestions may be wrong, they
    only need to be close enough for a human to confirm. Requires pg_trgm;
    returns [] without it.
    """
    from src.settings import LAW_TRGM_THRESHOLD

    if not has_trgm(db):
        return []
    conn = connect(db)
    try:
        floor = max(LAW_TRGM_THRESHOLD - 0.2, 0.24)
        return conn.execute(
            "SELECT id, title, status, "
            "similarity(regexp_replace(title, '^中华人民共和国', ''), %s) AS sim "
            "FROM law_catalog.laws "
            "WHERE similarity(regexp_replace(title, '^中华人民共和国', ''), %s) >= %s "
            "ORDER BY sim DESC LIMIT %s",
            (name, name, floor, limit),
        ).fetchall()
    finally:
        conn.close()
