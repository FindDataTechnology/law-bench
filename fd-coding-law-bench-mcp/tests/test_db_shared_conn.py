"""Tests for the process-wide cached connection helper in `src.eval.db`.

Hermetic: ``psycopg.connect`` is monkeypatched so no real DB is needed. Verifies
lazy open, reuse across calls, and that ``close_shared_conn()`` forces a reopen.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def _reset_shared_conn(monkeypatch):
    """Reset the cached connection slot before/after each test, and stub psycopg."""
    import src.eval.db as db_mod

    class FakeConn:
        def __init__(self, tag):
            self.tag = tag
            self.closed = False

        def close(self):
            self.closed = True

    counter = {"n": 0}

    def fake_connect(*args, **kwargs):
        counter["n"] += 1
        return FakeConn(counter["n"])

    import psycopg
    monkeypatch.setattr(psycopg, "connect", fake_connect)
    # Reset the module-level cache.
    db_mod._SHARED_CONN = None
    yield counter
    db_mod._SHARED_CONN = None


def test_get_shared_conn_opens_once_and_reuses(_reset_shared_conn):
    import src.eval.db as db_mod

    first = db_mod.get_shared_conn()
    second = db_mod.get_shared_conn()
    assert first is second
    assert first.tag == 1
    assert _reset_shared_conn["n"] == 1  # psycopg.connect called exactly once


def test_close_shared_conn_forces_reopen(_reset_shared_conn):
    import src.eval.db as db_mod

    first = db_mod.get_shared_conn()
    assert first.tag == 1
    db_mod.close_shared_conn()
    assert first.closed is True
    second = db_mod.get_shared_conn()
    assert second is not first
    assert second.tag == 2
    assert _reset_shared_conn["n"] == 2


def test_connect_routes_default_through_shared(_reset_shared_conn):
    import src.eval.db as db_mod

    wrapped = db_mod.connect()
    assert isinstance(wrapped, db_mod._BorrowedConn)
    # BorrowedConn.close() is a no-op - does not kill the underlying shared conn.
    wrapped.close()
    shared = db_mod.get_shared_conn()
    assert shared.closed is False
    assert _reset_shared_conn["n"] == 1  # only one underlying open
