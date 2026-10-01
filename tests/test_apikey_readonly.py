"""Tests for the read-replica-safe ``last_used_at`` guard (OpenSpec task 2.3).

Two regimes are under test:

- ``READONLY_REPLICA=1`` (the China public pod): :func:`verify_key` MUST NOT
  issue the ``UPDATE api_keys SET last_used_at`` write at all — the replica is
  read-only, so a per-request touch would only emit OperationalError noise.
  The key still authenticates (returns the user dict, not ``None``).

- ``READONLY_REPLICA=0`` (the origin, or any writeable DB): the best-effort
  touch runs. If it raises (a read-only standby rejects the write, the
  connection drops, etc.) the error is swallowed + debug-logged and the
  request STILL authenticates — a failed audit touch SHALL NOT cause 401/500.

Both use the REAL ``apikey`` module against the seeded Postgres DB (real
hash/verify, real create_key commit). ``_touch_last_used`` is intercepted with
a spy/mock so the assertion is on *whether the UPDATE is issued*, not on the
row's timestamp (which would be racy and indirect). The HTTP tests reuse the
public-app factory (no Logto probe needed) so the key-only posture is exercised
end-to-end.

Fixture note: the direct (non-HTTP) tests take ``seeded_db`` and pass it
explicitly as ``db_path`` to ``create_key``/``verify_key``. This routes through
the borrowed-connection path (a live conn injected, ``close()`` a no-op) so
the call is bound to the session DB regardless of test ordering — without it,
the default ``db_path`` resolves the process-wide ``get_shared_conn()`` which
caches a connection *before* ``_session_db_name`` has set up the session DB,
pointing it at the dev database and leaving the session DB without its schema.
The HTTP tests are order-safe via ``public_client`` → ``seeded_db``.
"""

from __future__ import annotations

import psycopg
import pytest
from fastapi.testclient import TestClient

from src.web.auth import apikey
from src.web.deps import get_db
from src.web.public_app import create_public_app


@pytest.fixture
def public_client(seeded_db) -> TestClient:
    """Public-app TestClient with the REAL ``get_current_user`` (key-only).

    Mirrors the ``public_client`` fixture in test_public_app.py: auth is NOT
    bypassed (no override of ``get_current_user``), ``get_db`` is overridden to
    the seeded DB so route handlers read the throwaway DB, and no Logto probe
    is needed (the public factory's startup runs ``check_public_auth_config``,
    not ``verify_reachable``). API-key create/verify resolve ``DEFAULT_DB`` ->
    the shared session-DB connection (established by ``seeded_db`` ->
    ``_session_db_name`` before this client is built), so a key committed by
    ``create_key`` is visible to ``verify_key``.
    """
    app = create_public_app()
    app.dependency_overrides[get_db] = lambda: seeded_db
    with TestClient(app) as client:
        yield client


def _boom(*_args, **_kwargs):
    """Stand-in for ``_touch_last_used`` that simulates a read-only standby."""
    raise psycopg.OperationalError(
        "cannot execute UPDATE in a read-only transaction"
    )


# --- READONLY_REPLICA=1: the UPDATE is skipped, the key still works --------- #


def test_readonly_replica_skips_last_used_update(seeded_db, monkeypatch):
    """With READONLY_REPLICA=1, verify_key MUST NOT call _touch_last_used.

    A spy replaces _touch_last_used and counts invocations; it must stay at 0.
    The key still authenticates (the returned dict carries the owner's sub).
    This is the China public pod's posture — the replica is read-only, so a
    per-request UPDATE would only log error noise against the standby.

    ``db_path=seeded_db`` binds the call to the session DB (borrowed conn)
    so the assertion does not depend on shared-connection ordering.
    """
    monkeypatch.setattr(apikey, "READONLY_REPLICA", True)

    calls = {"n": 0}

    def _spy(key_id, db_path):  # noqa: ANN001 — mirrors _touch_last_used's sig
        calls["n"] += 1

    monkeypatch.setattr(apikey, "_touch_last_used", _spy)

    plaintext = apikey.create_key("ro-user", "ro-replica", ["*"], db_path=seeded_db)
    resolved = apikey.verify_key(plaintext, db_path=seeded_db)

    assert resolved is not None, "READONLY_REPLICA must not break authentication"
    assert resolved["sub"] == "ro-user"
    assert calls["n"] == 0, "verify_key issued an UPDATE on a read-only replica"


def test_readonly_replica_http_still_200(monkeypatch, public_client: TestClient):
    """End-to-end on the public app: with READONLY_REPLICA=1, a valid key gets
    200 and _touch_last_used is never called."""
    monkeypatch.setattr(apikey, "READONLY_REPLICA", True)

    calls = {"n": 0}

    def _spy(key_id, db_path):  # noqa: ANN001
        calls["n"] += 1

    monkeypatch.setattr(apikey, "_touch_last_used", _spy)

    plaintext = apikey.create_key("ro-user", "ro-http", ["*"])
    r = public_client.get("/api/contracts/sale", headers={"X-API-Key": plaintext})
    assert r.status_code == 200
    assert calls["n"] == 0


# --- READONLY_REPLICA=0: a failed touch is swallowed, request still works --- #


def test_writeable_db_swallows_touch_operational_error(seeded_db, monkeypatch):
    """With READONLY_REPLICA=0 and _touch_last_used raising OperationalError
    (simulated read-only standby / connection loss), verify_key MUST swallow
    the error and still authenticate — a failed audit touch never causes 401.

    The error is narrowed to ``psycopg.OperationalError`` (with a bare-Exception
    safety net), so this also covers the generic-exception path.
    """
    monkeypatch.setattr(apikey, "READONLY_REPLICA", False)
    monkeypatch.setattr(apikey, "_touch_last_used", _boom)

    plaintext = apikey.create_key("rw-user", "touch-fails", ["*"], db_path=seeded_db)
    resolved = apikey.verify_key(plaintext, db_path=seeded_db)

    assert resolved is not None, "a failed last_used_at touch must not fail auth"
    assert resolved["sub"] == "rw-user"


def test_writeable_db_touch_failure_http_still_200(
    monkeypatch, public_client: TestClient
):
    """End-to-end on the public app: with READONLY_REPLICA=0 and the touch
    raising OperationalError on every call, a valid key still gets 200. The
    request proceeds on a verified key; the audit write's failure is invisible
    to the caller."""
    monkeypatch.setattr(apikey, "READONLY_REPLICA", False)
    monkeypatch.setattr(apikey, "_touch_last_used", _boom)

    plaintext = apikey.create_key("rw-user", "touch-fails-http", ["*"])
    r = public_client.get("/api/contracts/sale", headers={"X-API-Key": plaintext})
    assert r.status_code == 200
