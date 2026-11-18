"""Shared corpus libraries: libraries, sources, subscriptions, vector chunks.

Change ``add-domain-tree-and-shared-libraries``. Three ideas, one module:

- **Library** — the physical corpus unit (one embedding space + a source list).
  It exists independently of the domain tree: create the library first, then
  let domains subscribe.
- **Source** — one addressable slice of a library (object-store prefix, dataset
  id, …) with its own ingest rule. Ingest runs once per source, never once per
  subscribing domain.
- **Subscription** — a domain's claim on a library (optionally narrowed to a
  subset of its sources). Subscriptions are inherited down the domain tree:
  a child automatically gets its parent's effective sources and may only
  NARROW them. A child may not subscribe a library its parent does not have —
  that would let a sub-domain reach content the parent never granted.

A library is either **owned** or **external**:

- ``array-cosine`` / ``pgvector`` — owned. Content is ingested into
  ``corpus_chunks`` here, one vector per library, scope = the ingesting domain.
- ``qdrant`` / ``pgvector-external`` — external. The vectors already exist in a
  store this app does not own (the law corpus in Qdrant, the text engine's
  pgvector verticals); the library only records *where* to read (``location``)
  and each source says *which slice* (``ingest_rule``). Nothing is copied, and
  no row is written to ``corpus_chunks`` — so the gap matrix counts the remote
  store instead (``library_index.count_scope``).

``location`` never contains a secret: it names **environment variables**
(``{"url_env": "QDRANT_URL"}``, ``{"dsn_env": "FDTEXT_DATABASE_URL"}``) that are
resolved at query time. Credentials in the database would leak into dump
restores, console pages and commit history.

The vector column is ``float4[]`` and similarity is computed in Python, because
the deployed Postgres image (``postgres:16-alpine``) carries no pgvector
extension. This is a deliberate, documented compromise: the observable contract
(one shared embedding per library, subtree-scoped filtered retrieval) is the
same, and swapping the storage to pgvector later is a local change inside this
module.

There is no migration framework here: every statement must stay idempotent, and
``src.eval.store.ensure_schema`` executes ``LIBRARY_SCHEMA`` on first connect.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from psycopg.types.json import Jsonb

#: Accepted retrieval backends for a library. ``array-cosine`` is what this
#: deployment can actually serve for *owned* content (no pgvector in the image);
#: the value is stored explicitly so a later backend move is a data change, not
#: a guess. ``qdrant``/``pgvector-external`` are read-only adapters onto stores
#: that already hold vectors (the law corpus, the text engine's verticals).
BACKENDS = ("array-cosine", "pgvector", "qdrant", "pgvector-external")

#: Backends whose content lives outside this database. Nothing is ingested for
#: them and ``corpus_chunks`` stays empty by design.
EXTERNAL_BACKENDS = ("qdrant", "pgvector-external")


LIBRARY_SCHEMA = """
-- ── domain tree ──────────────────────────────────────────────────────────────
-- parent_id + path: a materialized path ('legal', 'legal/contract-review')
-- makes "this domain and its whole subtree" one indexed prefix scan. Depth is
-- small (<=4), so a closure table or recursive CTE would buy nothing.
ALTER TABLE IF EXISTS domains ADD COLUMN IF NOT EXISTS parent_id BIGINT REFERENCES domains(id);
ALTER TABLE IF EXISTS domains ADD COLUMN IF NOT EXISTS path TEXT;

-- Archiving is a soft exit: the domain leaves the estate, its data stays put.
-- A timestamp (not a boolean) because "when did this line stop" is the question
-- that actually gets asked later, and it matches the other soft-deletes in this
-- schema (domain_members.removed_at).
ALTER TABLE IF EXISTS domains ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;

-- Backfill: a pre-tree domain is a root whose path is its own key. Idempotent —
-- only rows that have never been assigned a path are touched again.
UPDATE domains SET path = key WHERE path IS NULL OR path = '';

CREATE UNIQUE INDEX IF NOT EXISTS domains_path_uk ON domains (path);
CREATE INDEX IF NOT EXISTS domains_parent_idx ON domains (parent_id);

-- ── libraries ────────────────────────────────────────────────────────────────
-- dims + backend are frozen per library: changing the embedding model means a
-- new library (and a re-ingest), never a silent in-place dimension change.
CREATE TABLE IF NOT EXISTS libraries (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    library_key      TEXT NOT NULL UNIQUE,
    name             TEXT NOT NULL,
    backend          TEXT NOT NULL DEFAULT 'array-cosine',
    embedding_model  TEXT,
    dims             INTEGER NOT NULL DEFAULT 2048 CHECK (dims > 0),
    created_by       TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Backends grew from two to four when the real corpora were registered
-- (Qdrant law corpus, the text engine's pgvector verticals). The first release
-- shipped a CHECK with only the owned backends, so a deployed table would
-- reject every external library — widen it in place rather than recreate.
-- ADD CONSTRAINT is not idempotent, so both the drop and the add are guarded.
ALTER TABLE IF EXISTS libraries DROP CONSTRAINT IF EXISTS libraries_backend_check;
DO $lib$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'libraries_backend_check'
           AND conrelid = to_regclass('public.libraries')
    ) THEN
        EXECUTE 'ALTER TABLE libraries ADD CONSTRAINT libraries_backend_check
                 CHECK (backend IN (''array-cosine'', ''pgvector'',
                                    ''qdrant'', ''pgvector-external''))';
    END IF;
END
$lib$;

-- Where an external library reads from. Holds **env var names**, never a DSN or
-- a key: this column is dumped, rendered and committed around, so a secret here
-- would leak through all three. Owned libraries keep this empty.
ALTER TABLE IF EXISTS libraries ADD COLUMN IF NOT EXISTS location JSONB NOT NULL DEFAULT '{}'::jsonb;

-- One source = one addressable slice with its own ingest rule. uri is opaque
-- to this module (object-store prefix, dataset id, …); source_kind says which
-- reader to use.
CREATE TABLE IF NOT EXISTS library_sources (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    library_id   BIGINT NOT NULL REFERENCES libraries(id),
    source_key   TEXT NOT NULL,
    uri          TEXT NOT NULL,
    source_kind  TEXT NOT NULL DEFAULT 'object-prefix',
    content_type TEXT,
    ingest_rule  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by   TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (library_id, source_key)
);

-- A subscription is a domain's claim on a library. source_filter NULL means
-- "every source in this library"; an explicit array is the narrowed subset.
-- The narrowing rule (child ⊆ parent) is enforced in effective_sources(), not
-- here: the DB cannot express "start from the parent's set".
CREATE TABLE IF NOT EXISTS domain_library_subscriptions (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain_id     BIGINT NOT NULL REFERENCES domains(id),
    library_id    BIGINT NOT NULL REFERENCES libraries(id),
    source_filter JSONB,
    created_by    TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (domain_id, library_id)
);

-- ── chunks ───────────────────────────────────────────────────────────────────
-- scope_path is the domain path the chunk was ingested FOR (the owning domain
-- that ran the ingest). Retrieval filters on the reader's effective subtree,
-- so one physical chunk serves the whole tree.
CREATE TABLE IF NOT EXISTS corpus_chunks (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    library_id   BIGINT NOT NULL REFERENCES libraries(id),
    scope_path   TEXT NOT NULL,
    source_key   TEXT NOT NULL,
    doc_path     TEXT NOT NULL,
    chunk_seq    INTEGER NOT NULL,
    content      TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    embedding    REAL[],
    meta         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (library_id, doc_path, chunk_seq)
);

CREATE INDEX IF NOT EXISTS corpus_chunks_scope_idx
    ON corpus_chunks (library_id, scope_path);
CREATE INDEX IF NOT EXISTS corpus_chunks_hash_idx
    ON corpus_chunks (library_id, content_hash);

-- ── domain-scoped knowledge units & rubrics ──────────────────────────────────
-- namespace was always the scoping axis (its unique key is
-- (kind, namespace, external_key)); this change makes domain paths the values.
ALTER TABLE IF EXISTS knowledge_units ADD COLUMN IF NOT EXISTS derived_from JSONB;

-- Pre-domain rows were written under the catch-all namespace. Point them at the
-- single pre-existing domain (there is exactly one in every deployed database:
-- the retro-registered legal domain).
UPDATE knowledge_units SET namespace = (
    SELECT path FROM domains ORDER BY id LIMIT 1
) WHERE namespace = 'default';

-- rubrics had no owner at all; evaluation standards are per-domain now.
-- eval_runs learns which rubric (and thus which domain) each run actually used;
-- nullable because legacy runs predate ownership and must not be re-attributed.
-- `domain_id`/`derived_from` are plain BIGINT, not foreign keys: the deployed
-- `rubrics` table has no primary key (legacy script), and a boot-time FK here
-- crash-looped production on 2026-11-08. Referential integrity for the fork
-- link is by convention; the parent domain's own PK is still enforced where it
-- lives (domains).
ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS rubric_domain_id BIGINT;
ALTER TABLE IF EXISTS rubrics ADD COLUMN IF NOT EXISTS domain_id BIGINT;
-- Soft reference, deliberately NOT a foreign key: the deployed `rubrics` table
-- was created by a legacy script and carries no primary key at all (verified in
-- production 2026-11-08), so `REFERENCES rubrics(id)` fails the unique-constraint
-- requirement and takes the whole boot down. A fork pointing at a since-deleted
-- parent is still meaningful history, so integrity here is by convention.
ALTER TABLE IF EXISTS rubrics ADD COLUMN IF NOT EXISTS derived_from BIGINT;
ALTER TABLE IF EXISTS rubrics ADD COLUMN IF NOT EXISTS fork_diff JSONB;

-- rubrics is created by a legacy schema constant that may run after this one
-- on a fresh database, so the backfill and its index are guarded by existence.
DO $lib$
BEGIN
    IF to_regclass('public.rubrics') IS NOT NULL THEN
        UPDATE rubrics SET domain_id = (
            SELECT id FROM domains ORDER BY id LIMIT 1
        ) WHERE domain_id IS NULL;
        EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS rubrics_domain_name_uk
                 ON rubrics (domain_id, name)';
    END IF;
END
$lib$;
"""


# ── libraries ────────────────────────────────────────────────────────────────


def create_library(
    conn: Any,
    *,
    library_key: str,
    name: str,
    created_by: str,
    backend: str = "array-cosine",
    embedding_model: Optional[str] = None,
    dims: int = 2048,
    location: Optional[dict] = None,
) -> dict:
    """Create one library. The key is the stable identity and never changes.

    ``location`` addresses an external store with env var *names*:

    - ``qdrant``: ``{"url_env": "QDRANT_URL", "collection": "law_chunks_v2"}``
    - ``pgvector-external``: ``{"dsn_env": "FDTEXT_DATABASE_URL"}``

    Environment names, not values: see the module docstring.
    """
    library_key = (library_key or "").strip()
    if not library_key:
        raise ValueError("library_key is required")
    if backend not in BACKENDS:
        raise ValueError(f"backend must be one of {list(BACKENDS)}")
    if not isinstance(dims, int) or dims <= 0:
        raise ValueError("dims must be a positive integer")
    loc = dict(location or {})
    if backend in EXTERNAL_BACKENDS:
        needed = "url_env" if backend == "qdrant" else "dsn_env"
        if not loc.get(needed):
            raise ValueError(f"{backend} library requires location[{needed!r}] (env var name)")
        if backend == "qdrant" and not loc.get("collection"):
            raise ValueError("qdrant library requires location['collection']")
    cur = conn.execute(
        """
        INSERT INTO libraries
            (library_key, name, backend, embedding_model, dims, location, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id, library_key, name, backend, embedding_model, dims, location,
                  created_by, created_at
        """,
        (
            library_key,
            name or library_key,
            backend,
            embedding_model,
            dims,
            Jsonb(loc),
            created_by,
        ),
    )
    row = _row(cur.fetchone())
    conn.commit()
    return _with_location(row)


def add_source(
    conn: Any,
    *,
    library_key: str,
    source_key: str,
    uri: str,
    created_by: str,
    source_kind: str = "object-prefix",
    content_type: Optional[str] = None,
    ingest_rule: Optional[dict] = None,
) -> dict:
    """Register one source on a library (idempotent per (library, source_key))."""
    lib = get_library(conn, library_key=library_key)
    if lib is None:
        raise ValueError(f"library {library_key!r} not found")
    cur = conn.execute(
        """
        INSERT INTO library_sources
            (library_id, source_key, uri, source_kind, content_type, ingest_rule, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id, source_key, uri, source_kind, content_type, ingest_rule
        """,
        (
            lib["id"],
            source_key,
            uri,
            source_kind,
            content_type,
            Jsonb(ingest_rule or {}),
            created_by,
        ),
    )
    row = _row(cur.fetchone())
    conn.commit()
    return row


def get_library(conn: Any, *, library_key: str) -> Optional[dict]:
    return _with_location(
        _row(
            conn.execute(
                "SELECT id, library_key, name, backend, embedding_model, dims, location "
                "FROM libraries WHERE library_key = %s",
                (library_key,),
            ).fetchone()
        )
    )


def list_libraries(conn: Any) -> list[dict]:
    """Every registered library with its source count, for the console."""
    return [
        _with_location(dict(r))
        for r in conn.execute(
            "SELECT l.id, l.library_key, l.name, l.backend, l.embedding_model, l.dims, "
            "       l.location, "
            "       (SELECT COUNT(*) FROM library_sources s WHERE s.library_id = l.id) "
            "       AS source_count "
            "FROM libraries l ORDER BY l.library_key"
        ).fetchall()
    ]


def list_sources(conn: Any, *, library_id: int) -> list[dict]:
    return [
        _row(r)
        for r in conn.execute(
            "SELECT source_key, uri, source_kind, content_type, ingest_rule "
            "FROM library_sources WHERE library_id = %s ORDER BY source_key",
            (library_id,),
        ).fetchall()
    ]


# ── subscriptions ────────────────────────────────────────────────────────────


def subscribe(
    conn: Any,
    *,
    domain_id: int,
    library_key: str,
    created_by: str,
    source_filter: Optional[Iterable[str]] = None,
) -> dict:
    """Declare (or replace) a domain's subscription to one library.

    ``source_filter=None`` means every source. Narrowing against the parent is
    validated by :func:`effective_sources` — this function only stores the
    claim, because the parent's set may legitimately change later.
    """
    lib = get_library(conn, library_key=library_key)
    if lib is None:
        raise ValueError(f"library {library_key!r} not found")
    filt = None if source_filter is None else sorted({str(s) for s in source_filter if s})
    known = {s["source_key"] for s in list_sources(conn, library_id=lib["id"])}
    if filt is not None:
        unknown = [s for s in filt if s not in known]
        if unknown:
            raise ValueError(f"unknown source(s) for {library_key!r}: {', '.join(unknown)}")
    cur = conn.execute(
        """
        INSERT INTO domain_library_subscriptions (domain_id, library_id, source_filter, created_by)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (domain_id, library_id) DO UPDATE
            SET source_filter = excluded.source_filter, created_by = excluded.created_by
        RETURNING id, domain_id, library_id, source_filter
        """,
        (domain_id, lib["id"], None if filt is None else Jsonb(filt), created_by),
    )
    row = _row(cur.fetchone())
    conn.commit()
    return row


def narrow(
    conn: Any,
    *,
    domain_id: int,
    domain_path: str,
    library_key: str,
    sources: Iterable[str],
    created_by: str,
) -> dict:
    """Narrow a domain's own subscription, refusing anything that widens.

    ``subscribe`` stores whatever it is given and lets ``effective_sources``
    complain later — fine for an admin form, wrong for a self-service page: the
    domain lead would see a success flash and a broken scope on the next page
    load. Validating **here** turns "you may not do that" into an immediate,
    specific error.

    Rules, matching the resolver exactly:

    - a root domain may narrow to any subset of the library's sources;
    - a child may only pick from what its **parent** effectively holds, and the
      library itself must be one the parent holds.
    """
    lib = get_library(conn, library_key=library_key)
    if lib is None:
        raise ValueError(f"library {library_key!r} not found")
    wanted = {str(s).strip() for s in sources if str(s).strip()}
    if not wanted:
        raise ValueError("narrowing needs at least one source; omit the filter to keep every source")
    known = {s["source_key"] for s in list_sources(conn, library_id=lib["id"])}
    unknown = sorted(wanted - known)
    if unknown:
        raise ValueError(f"unknown source(s) for {library_key!r}: {', '.join(unknown)}")

    parent_path = "/".join([p for p in (domain_path or "").split("/") if p][:-1])
    if parent_path:
        parent_scope = effective_sources(conn, domain_path=parent_path)
        if library_key not in parent_scope:
            raise ValueError(
                f"the parent domain does not hold {library_key!r} — a sub-domain cannot "
                "introduce a library its parent never granted"
            )
        extra = sorted(wanted - parent_scope[library_key])
        if extra:
            raise ValueError(
                f"scope widens beyond the parent: {', '.join(extra)} not granted by {parent_path!r}"
            )
    return subscribe(
        conn,
        domain_id=domain_id,
        library_key=library_key,
        created_by=created_by,
        source_filter=sorted(wanted),
    )


def _ancestors(path: str) -> list[str]:
    """``legal/a/b`` → ``['legal', 'legal/a', 'legal/a/b']`` (root first)."""
    parts = [p for p in (path or "").split("/") if p]
    return ["/".join(parts[: i + 1]) for i in range(len(parts))]


def effective_sources(conn: Any, *, domain_path: str) -> dict[str, set[str]]:
    """Resolve a domain's effective retrieval scope.

    Returns ``{library_key: {source_key, …}}``. Rules, applied root → leaf:

    - a root domain's own subscription is its effective set;
    - a child inherits its parent's effective set per library;
    - a child may require a subset (``source_filter``) of an inherited set —
      narrowing only;
    - a child may NOT introduce a library its parent does not have, and may not
      name a source outside the inherited subset.

    Raises ``ValueError`` when a stored subscription violates those rules, so a
    scope can never silently widen.
    """
    path = (domain_path or "").strip().strip("/")
    if not path:
        raise ValueError("domain_path is required")

    rows = conn.execute(
        """
        SELECT d.path, d.id, l.library_key, s.source_filter
          FROM domains d
          JOIN domain_library_subscriptions s ON s.domain_id = d.id
          JOIN libraries l ON l.id = s.library_id
         WHERE d.path = ANY(%s)
        """,
        (_ancestors(path),),
    ).fetchall()
    by_path: dict[str, dict[str, Optional[set[str]]]] = {}
    for r in rows:
        filt = r["source_filter"]
        if isinstance(filt, str):
            filt = json.loads(filt)
        by_path.setdefault(r["path"], {})[r["library_key"]] = (
            None if filt is None else set(filt)
        )

    effective: dict[str, set[str]] = {}
    for ancestor in _ancestors(path):
        own = by_path.get(ancestor, {})
        for lib_key, filt in own.items():
            if lib_key not in effective:
                # First appearance in this chain: it must be a root-level grant.
                if ancestor != _ancestors(path)[0]:
                    raise ValueError(
                        f"library {lib_key!r} is subscribed by {ancestor!r} but not by its parent — "
                        "a sub-domain cannot widen its parent's scope"
                    )
                effective[lib_key] = _library_source_set(conn, lib_key) if filt is None else set(filt)
                continue
            if filt is None:
                continue  # keep inherited set unchanged
            extra = filt - effective[lib_key]
            if extra:
                raise ValueError(
                    f"scope for {ancestor!r} widens library {lib_key!r}: "
                    f"{', '.join(sorted(extra))} not granted by the parent"
                )
            effective[lib_key] = filt
    return effective


def _library_source_set(conn: Any, library_key: str) -> set[str]:
    return {
        r["source_key"]
        for r in conn.execute(
            "SELECT s.source_key FROM library_sources s "
            "JOIN libraries l ON l.id = s.library_id WHERE l.library_key = %s",
            (library_key,),
        ).fetchall()
    }


def _row(row: Any) -> Optional[dict]:
    if row is None:
        return None
    return dict(row) if isinstance(row, dict) else dict(row)


def _with_location(row: Optional[dict]) -> Optional[dict]:
    """Decode ``location`` from JSONB text (psycopg may hand back a string)."""
    if not row:
        return row
    loc = row.get("location")
    if isinstance(loc, (str, bytes)):
        row["location"] = json.loads(loc or "{}")
    elif loc is None:
        row["location"] = {}
    return row


def resolve_location(lib: dict, *, env: Any = None) -> dict:
    """Turn a library's env *names* into the values a client needs.

    Raises ``ValueError`` naming the missing variable rather than returning a
    half-filled location — a library that cannot be resolved must fail loudly at
    query time, not silently search nothing.
    """
    import os

    source = env if env is not None else os.environ
    loc = dict(lib.get("location") or {})
    resolved = dict(loc)
    for key in ("url_env", "dsn_env"):
        name = loc.get(key)
        if name:
            value = source.get(name)
            if not value:
                raise ValueError(
                    f"library {lib.get('library_key')!r} needs environment variable {name!r}, "
                    "which is not set"
                )
            resolved[key] = value
    return resolved
