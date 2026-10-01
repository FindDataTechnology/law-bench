"""Low-level PostgreSQL helpers shared by the eval manage and store layers.

Centralizes connection setup (dict-row factory, single source of truth = the
``database_url`` env var), the UTC timestamp helper, the harbor-provenance
predicate, and criterion renumbering, so the CRUD modules and the run-store do
not each redefine them.

Connection model: ``connect(db)`` is a passthrough-or-open factory. If ``db``
is already a live ``psycopg`` connection (e.g. injected by a test fixture or a
request dependency), it is returned unchanged; otherwise a new connection is
opened from the ``database_url`` environment variable. The historical
``db_path`` parameter name is retained across the CRUD/store surface for
call-site compatibility, but it now carries an *optional connection* - a
filesystem path is no longer used (PostgreSQL is addressed by DSN).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

from dotenv import load_dotenv

from src.settings import ConfigError


class _BorrowedConn:
    """Wrap a connection so ``close()`` is a no-op.

    CRUD/store functions open a connection, use it, and ``close()`` it in a
    ``finally``. When a *request* (via ``get_db``) or a *test* injects a shared
    connection, that borrower must not close it - the owner (the request scope
    or the test fixture) manages its lifetime. This proxy delegates
    ``execute``/``commit`` (and anything else via ``__getattr__``) to the real
    connection while making ``close()`` a no-op, so the existing
    ``try/finally: conn.close()`` pattern is safe for both owned and borrowed
    connections.
    """

    def __init__(self, conn) -> None:
        self._conn = conn

    def execute(self, *args, **kwargs):
        return self._conn.execute(*args, **kwargs)

    def commit(self, *args, **kwargs):
        return self._conn.commit(*args, **kwargs)

    def close(self) -> None:  # borrower does not own the connection
        pass

    def __getattr__(self, name):
        return getattr(self._conn, name)


def is_connection(obj) -> bool:
    """True if ``obj`` looks like a live DB connection (duck-typed)."""
    return obj is not None and hasattr(obj, "execute") and hasattr(obj, "commit")


def _dsn() -> str:
    """The PostgreSQL DSN from env (``database_url`` or ``DATABASE_URL``)."""
    load_dotenv()
    dsn = os.environ.get("database_url") or os.environ.get("DATABASE_URL")
    if not dsn:
        raise ConfigError(
            "database_url is not set (expected a PostgreSQL DSN, e.g. "
            "postgresql://user:pass@host:5432/db)."
        )
    return dsn


def _open_fresh() -> Any:
    """Open a brand-new psycopg connection from the DSN (keepalives enabled).

    Shared by :func:`connect`'s non-cached path and :func:`open_fresh_conn`.
    """
    import psycopg  # local import keeps module import light
    from psycopg.rows import dict_row

    # Add TCP keepalive parameters to prevent connection timeout during long LLM calls
    dsn = _dsn()
    if 'keepalives=' not in dsn:
        separator = '&' if '?' in dsn else '?'
        dsn = f"{dsn}{separator}keepalives=1&keepalives_idle=60&keepalives_interval=10&keepalives_count=5"
    return psycopg.connect(dsn, row_factory=dict_row)


def open_fresh_conn() -> Any:
    """Open a new connection the caller owns (no caching, no borrowing).

    For worker threads that need an isolated connection - e.g. the web batch
    pool, where the request-scoped connection (and the process-wide shared
    connection) must not cross threads. Caller closes it.
    """
    return _open_fresh()


def connect(db: Any = None) -> Any:
    """Return a psycopg connection (or a borrowed-connection wrapper).

    If ``db`` is already a live connection (e.g. injected by a request
    dependency or a test fixture), return a ``_BorrowedConn`` wrapping it so the
    caller's ``finally: conn.close()`` does not close the shared connection.
    Otherwise, when ``db`` is ``None`` or the legacy ``DEFAULT_DB`` sentinel,
    return the process-wide cached connection via :func:`get_shared_conn` so
    repeated callers reuse one TCP connection instead of opening a fresh one
    per call. Any other non-connection ``db`` value is ignored and a fresh
    connection is opened from the DSN.
    """
    if is_connection(db):
        return _BorrowedConn(db)
    # ponytail: default-arg path routes through the cached connection. Callers
    # that pass an explicit non-default path still get a fresh connection
    # (legacy behavior, no production caller does this today).
    if db is None:
        return _BorrowedConn(get_shared_conn())
    try:
        from src.settings import DEFAULT_DB
        if db is DEFAULT_DB or db == DEFAULT_DB:
            return _BorrowedConn(get_shared_conn())
    except Exception:  # noqa: BLE001 - settings import failure -> fall through to fresh conn
        pass
    return _open_fresh()


# --- Process-wide cached connection (ponytail: global conn, reopen on failure) ---
#
# The MCP server wraps every tool in `anyio.to_thread.run_sync`, so the event
# loop is free while a worker thread blocks on psycopg. Opening a fresh TCP
# connection per tool call is pure overhead; a single cached connection reused
# across calls removes the per-call connect/auth cost. If the DB restarts, the
# cached connection goes stale - the next tool call surfaces that as a tool
# error; restart the MCP server (or call `close_shared_conn()` to force a
# reopen). Escalate to a pool only if contention shows up in practice.
_SHARED_CONN: Any = None


def _is_conn_alive(conn: Any) -> bool:
    """Check if a connection is still alive by testing its status."""
    if conn is None:
        return False
    try:
        # psycopg3 connections have an info.status attribute
        # 0 = CONNECTION_OK, other values indicate problems
        return hasattr(conn, 'info') and conn.info.status == 0
    except Exception:
        return False


def get_shared_conn() -> Any:
    """Return a process-wide cached psycopg connection, opening it lazily.

    If the cached connection has been terminated by the server (e.g., AdminShutdown),
    automatically reopen it.
    """
    global _SHARED_CONN
    if _SHARED_CONN is None or not _is_conn_alive(_SHARED_CONN):
        if _SHARED_CONN is not None:
            # Try to close the stale connection
            try:
                _SHARED_CONN.close()
            except Exception:
                pass
        import psycopg
        from psycopg.rows import dict_row
        # Add TCP keepalive parameters to prevent connection timeout during long LLM calls
        dsn = _dsn()
        # Parse and augment DSN with keepalive parameters if not already present
        if 'keepalives=' not in dsn:
            separator = '&' if '?' in dsn else '?'
            dsn = f"{dsn}{separator}keepalives=1&keepalives_idle=60&keepalives_interval=10&keepalives_count=5"
        _SHARED_CONN = psycopg.connect(dsn, row_factory=dict_row, autocommit=True)
    return _SHARED_CONN


def close_shared_conn() -> None:
    """Close the cached connection (if any); next `get_shared_conn()` reopens."""
    global _SHARED_CONN
    if _SHARED_CONN is not None:
        try:
            _SHARED_CONN.close()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass
        _SHARED_CONN = None


def now_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def is_harbor(source: Optional[str]) -> bool:
    """True if the rubric source marks it as a read-only harbor reference."""
    return bool(source) and source.startswith("harbor:")


def column_exists(conn, table: str, col: str) -> bool:
    """True if ``table`` has a column named ``col`` (PostgreSQL information_schema)."""
    row = conn.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = %s AND column_name = %s",
        (table, col),
    ).fetchone()
    return row is not None


def table_exists(conn, table: str) -> bool:
    """True if ``table`` exists in the public schema."""
    row = conn.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = %s",
        (table,),
    ).fetchone()
    return row is not None


def renumber_criteria(conn, rubric_id: int) -> None:
    """Reassign ordinal to be contiguous 0..N-1 in current order."""
    rows = conn.execute(
        "SELECT id FROM criteria WHERE rubric_id = %s ORDER BY ordinal, id",
        (rubric_id,),
    ).fetchall()
    for i, r in enumerate(rows):
        conn.execute(
            "UPDATE criteria SET ordinal = %s WHERE id = %s",
            (i, r["id"]),
        )
