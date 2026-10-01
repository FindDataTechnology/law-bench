"""FastAPI dependencies for the evaluation-rules web app.

``get_db`` is the seam that lets tests point the web layer at a throwaway
database via ``app.dependency_overrides[get_db] = ...`` instead of mutating the
development database. It returns a PostgreSQL connection resolved from the
``database_url`` environment variable (no longer a filesystem ``Path``); CRUD
functions borrow it without closing it (see ``src/eval/db._BorrowedConn``).

``DbConn`` is the runtime-checkable :class:`typing.Protocol` that both a real
``psycopg`` connection and the ``_BorrowedConn`` no-close wrapper satisfy. Route
handlers annotate their ``db`` parameter as ``DbConn`` instead of the legacy
``Path`` / ``Any`` so the type reflects what actually arrives at runtime — a
DB-API-2 connection — not the SQLite-era file path or an opaque value.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DbConn(Protocol):
    """Structural type for a PostgreSQL (DB-API-2 style) connection.

    Matches both a real ``psycopg`` connection and the
    :class:`src.eval.db._BorrowedConn` wrapper that makes ``close()`` a no-op so
    a request- or test-injected shared connection survives a callee's
    ``finally: conn.close()``. Duck-typed by :func:`src.eval.db.is_connection`
    via ``execute`` + ``commit``; the protocol mirrors that minimal surface and
    adds the context-manager dunders psycopg connections implement.
    """

    def execute(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - protocol
        """Run a query; returns a cursor-like object (``fetchone``/``fetchall``)."""
        ...

    def commit(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover - protocol
        """Commit the current transaction (no-op when autocommit is on)."""
        ...

    def close(self) -> None:  # pragma: no cover - protocol
        """Close the connection (a no-op on a borrowed/shared connection)."""
        ...

    def __enter__(self) -> "DbConn":  # pragma: no cover - protocol
        ...

    def __exit__(self, *exc: Any) -> None:  # pragma: no cover - protocol
        ...


def get_db() -> DbConn:
    """Return a PostgreSQL connection for the web layer to read/write.

    Opens a connection from ``database_url``. Tests override this through
    ``app.dependency_overrides[get_db]`` to inject a connection to a throwaway
    test database.
    """
    from src.eval.db import connect  # local import avoids a circular import at load

    return connect()
