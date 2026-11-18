"""Domain -> RAG corpus registry: index resolution, registration, lookup.

Each workspace domain may register exactly one retrieval corpus: the
Elasticsearch index it owns, the MinIO sources it is ingested from, and an
optional embedding-model declaration. Registration state lives in the
``rag_corpora`` table (DDL in ``src.bench.workspace_store``); this module is
the only read/write surface for it.

Resolution contract (:func:`resolve_index`):

- ``domain_key=None``  -> the global ``SEARCH_INDEX_NAME`` setting (the
  pre-registry behavior; every legacy call path passes no domain).
- ``'legal'``          -> the registered index when a ``rag_corpora`` row
  exists, else the global default. The legal domain predates the registry, so
  an unregistered legal domain must keep working unchanged (retro-compat).
- any other key        -> the registered index, or
  :class:`CorpusNotRegistered` naming the domain. Fail closed: an unregistered
  domain never falls back to the default index (that would leak another
  domain's corpus into its search results).

Index-name convention: a registered index must start with ``f"{domain_key}-"``
so two workspaces can never be pointed at one index by a typo (``legal`` is
exempt — its retro-registered index is the pre-registry global default).
Enforced by :func:`validate_index_name` at registration time.

All functions borrow a DB-API connection supplied by the caller (the project's
``src.eval.db.connect`` dict-row convention); this module never opens or closes
one. ``register_corpus`` commits once, at the end of the operation.
"""

from __future__ import annotations

from typing import Any, Optional

from psycopg.types.json import Jsonb

# The legal domain is the retro-compat key: unregistered it resolves to the
# global default index instead of failing.
LEGAL_DOMAIN_KEY = "legal"


class CorpusNotRegistered(ValueError):
    """The requested domain has no registered RAG corpus."""


_CORPUS_COLS = (
    "rc.id, rc.domain_id, d.key AS domain_key, rc.index_name, "
    "rc.sources, rc.embedding_model, rc.registered_by, rc.created_at"
)
_CORPUS_SELECT = (
    f"SELECT {_CORPUS_COLS} "
    "FROM rag_corpora rc JOIN domains d ON d.id = rc.domain_id"
)


def _default_index() -> str:
    """The global default index, read at call time.

    Function-time attribute read (not an import-time binding) so tests
    monkeypatching ``src.settings.SEARCH_INDEX_NAME`` are honored.
    """
    from src.settings import SEARCH_INDEX_NAME

    return SEARCH_INDEX_NAME


def validate_index_name(domain_key: str, index_name: str) -> None:
    """Enforce the ``{domain_key}-`` index-name convention.

    Raises ``ValueError`` unless ``index_name`` starts with
    ``f"{domain_key}-"``. The ``legal`` domain is exempt: its registered index
    may be any name (notably the pre-registry global default) so the zero-
    migration retro-registration stays possible.
    """
    if not domain_key or domain_key == LEGAL_DOMAIN_KEY:
        return
    prefix = f"{domain_key}-"
    if not index_name.startswith(prefix):
        raise ValueError(
            f"index_name {index_name!r} must start with {prefix!r} "
            f"so domain {domain_key!r} cannot be pointed at another domain's index"
        )


def _validate_sources(sources: Any) -> list[dict]:
    """Validate the source declarations; return the normalized list.

    A source is ``{"bucket": str, "prefix": str}`` with non-empty strings; the
    normalized form keeps exactly those two keys so the stored JSONB stays
    canonical. An empty list is valid (searchable-but-not-ingestible corpus).
    """
    if not isinstance(sources, list):
        raise ValueError("sources must be a list of {bucket, prefix} objects")
    normalized: list[dict] = []
    for i, src in enumerate(sources):
        if not isinstance(src, dict):
            raise ValueError(
                f"sources[{i}] must be an object with 'bucket' and 'prefix' keys"
            )
        bucket = src.get("bucket")
        prefix = src.get("prefix")
        if not isinstance(bucket, str) or not bucket.strip():
            raise ValueError(f"sources[{i}].bucket must be a non-empty string")
        if not isinstance(prefix, str) or not prefix.strip():
            raise ValueError(f"sources[{i}].prefix must be a non-empty string")
        normalized.append({"bucket": bucket, "prefix": prefix})
    return normalized


def _domain_id(conn: Any, domain_key: str) -> Optional[int]:
    row = conn.execute(
        "SELECT id FROM domains WHERE key = %s", (domain_key,)
    ).fetchone()
    if row is None:
        return None
    return row["id"] if isinstance(row, dict) else row[0]


def _row_to_dict(row: Any) -> dict:
    """Normalize a (dict-row) corpus row; ISO-stringify the timestamp."""
    out = dict(row)
    created = out.get("created_at")
    if hasattr(created, "isoformat"):
        out["created_at"] = created.isoformat()
    return out


def resolve_index(conn: Any, domain_key: str | None) -> str:
    """Resolve a domain key to the Elasticsearch index its search runs on.

    See the module docstring for the exact contract. Raises
    :class:`CorpusNotRegistered` for a non-legal domain without a registry row
    (``domain_key=None`` and unregistered ``legal`` fall back to the global
    default instead).
    """
    if domain_key is None:
        return _default_index()
    row = conn.execute(
        _CORPUS_SELECT + " WHERE d.key = %s", (domain_key,)
    ).fetchone()
    if row is not None:
        return row["index_name"]
    if domain_key == LEGAL_DOMAIN_KEY:
        # Retro-compat: legal predates the registry; until it is registered it
        # keeps the pre-registry global default index.
        return _default_index()
    raise CorpusNotRegistered(
        f"Domain {domain_key!r} has no registered RAG corpus; register one "
        f"with src.search.resolver.register_corpus before searching it."
    )


def register_corpus(
    conn: Any,
    *,
    domain_key: str,
    index_name: str,
    sources: list[dict],
    registered_by: str,
    embedding_model: Optional[str] = None,
) -> dict:
    """Register (or replace) a domain's corpus configuration.

    One row per domain: re-registering the same domain replaces its
    ``index_name`` / ``sources`` / ``embedding_model`` via
    ``ON CONFLICT (domain_id) DO UPDATE``. Validation (all ``ValueError``):

    - the domain must exist (``domains.key``);
    - ``index_name`` must be a non-empty string obeying the
      ``{domain_key}-`` prefix convention (:func:`validate_index_name`;
      ``legal`` exempt) and must not already belong to a *different* domain
      (the table-wide ``index_name`` UNIQUE constraint);
    - ``sources`` must be a list of ``{"bucket", "prefix"}`` objects with
      non-empty strings (empty list allowed);
    - ``registered_by`` must be a non-empty string.

    Returns the stored row (``sources`` decoded back to a list).
    """
    if not isinstance(index_name, str) or not index_name.strip():
        raise ValueError("index_name must be a non-empty string")
    if not isinstance(registered_by, str) or not registered_by.strip():
        raise ValueError("registered_by must be a non-empty string")
    normalized_sources = _validate_sources(sources)
    validate_index_name(domain_key, index_name)

    domain_id = _domain_id(conn, domain_key)
    if domain_id is None:
        raise ValueError(f"Domain {domain_key!r} does not exist")

    clash = conn.execute(
        "SELECT domain_id FROM rag_corpora WHERE index_name = %s", (index_name,)
    ).fetchone()
    if clash is not None:
        clash_domain_id = clash["domain_id"] if isinstance(clash, dict) else clash[0]
        if clash_domain_id != domain_id:
            raise ValueError(
                f"index_name {index_name!r} is already registered to another "
                f"domain; each domain must own a distinct index"
            )

    cur = conn.execute(
        """
        INSERT INTO rag_corpora
            (domain_id, index_name, sources, embedding_model, registered_by)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (domain_id) DO UPDATE
        SET index_name      = EXCLUDED.index_name,
            sources         = EXCLUDED.sources,
            embedding_model = EXCLUDED.embedding_model,
            registered_by   = EXCLUDED.registered_by
        RETURNING id, domain_id, index_name, sources, embedding_model,
                  registered_by, created_at
        """,
        (
            domain_id,
            index_name,
            Jsonb(normalized_sources),
            embedding_model,
            registered_by,
        ),
    )
    row = cur.fetchone()
    conn.commit()
    out = _row_to_dict(row)
    out["domain_key"] = domain_key
    return out


def get_corpus(conn: Any, *, domain_key: str) -> Optional[dict]:
    """One domain's corpus row, or ``None`` when it has none (or the domain
    itself does not exist — callers that must distinguish the two should check
    ``domains`` separately)."""
    row = conn.execute(
        _CORPUS_SELECT + " WHERE d.key = %s", (domain_key,)
    ).fetchone()
    return _row_to_dict(row) if row is not None else None


def list_corpora(conn: Any) -> list[dict]:
    """All registered corpora, ordered by domain key."""
    rows = conn.execute(_CORPUS_SELECT + " ORDER BY d.key").fetchall()
    return [_row_to_dict(r) for r in rows]
