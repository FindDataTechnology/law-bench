"""Tests for the ``/copilotkit`` admin-assistant proxy (change
``add-admin-copilot-assistant``).

Exercises the REAL ``require_scope("admin")`` gate on the router — no
dependency override — so 401 (unauthenticated) vs 403 (non-admin) vs 200
(admin, proxied+streamed) and the 503 (runtime unconfigured) fail-closed
behavior are actually under test. No runtime is hit: the upstream is an
``httpx.MockTransport`` handler that records what the proxy forwarded.
"""

from __future__ import annotations

import typing

import httpx
import pytest
from fastapi.testclient import TestClient

from src.settings import AUTH_COOKIE_NAME
from src.web.app import create_app
from src.web.auth import logto, session
from src.web.auth.scopes import scopes_from_claims
from src.web.deps import get_db
from src.web.routes import copilot as copilot_routes


@pytest.fixture
def proxy_client(seeded_db, monkeypatch) -> TestClient:
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: seeded_db
    with TestClient(app) as client:
        yield client


def _cookie(payload: dict) -> str:
    return session._serializer().dumps(session._normalize(payload))


def _login(client: TestClient, sub: str, scopes: list[str]) -> None:
    normalized = scopes_from_claims({"scope": " ".join(scopes)})
    client.cookies.set(AUTH_COOKIE_NAME, _cookie({"sub": sub, "scopes": normalized}))


# --- mock upstream --------------------------------------------------------- #

_RECORDS: dict = {}


async def _upstream_body() -> "typing.AsyncIterator[bytes]":
    # An async generator keeps the mock response unread until iterated, the
    # same semantics as a real socket — MockTransport's `content=bytes` form
    # is eagerly read and `aiter_raw` would see it as already consumed.
    yield b'{"data":'
    yield b'{"hello":"world"}}'


def _upstream(request: httpx.Request) -> httpx.Response:
    _RECORDS["method"] = request.method
    _RECORDS["url"] = str(request.url)
    _RECORDS["headers"] = dict(request.headers)
    _RECORDS["body"] = request.read().decode()
    return httpx.Response(
        200,
        content=_upstream_body(),
        headers={"content-type": "application/json"},
    )


@pytest.fixture
def runtime_configured(monkeypatch):
    """Point the proxy at a mock upstream and record what it forwards."""
    monkeypatch.setattr(copilot_routes, "COPILOT_RUNTIME_URL", "http://runtime.test:3111")
    monkeypatch.setattr(
        copilot_routes,
        "_build_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(_upstream),
            timeout=copilot_routes._TIMEOUT,
        ),
    )
    _RECORDS.clear()


# --- gating ---------------------------------------------------------------- #


def test_unauthenticated_is_rejected_before_proxying(proxy_client, monkeypatch):
    monkeypatch.setattr(copilot_routes, "COPILOT_RUNTIME_URL", "http://runtime.test:3111")
    resp = proxy_client.post("/copilotkit", json={})
    assert resp.status_code == 401
    assert not _RECORDS, "the runtime must not be reached without credentials"


def test_non_admin_session_gets_403(proxy_client, runtime_configured):
    _login(proxy_client, "viewer-1", ["content:read"])
    resp = proxy_client.post("/copilotkit", json={})
    assert resp.status_code == 403
    assert not _RECORDS, "the runtime must not be reached without the admin scope"


def test_runtime_unconfigured_is_503_even_for_admin(proxy_client, monkeypatch):
    monkeypatch.setattr(copilot_routes, "COPILOT_RUNTIME_URL", "")
    _login(proxy_client, "admin-1", ["admin"])
    resp = proxy_client.post("/copilotkit", json={})
    assert resp.status_code == 503
    assert "COPILOT_RUNTIME_URL" in resp.json()["error"]


# --- admin passthrough ------------------------------------------------------ #


def test_admin_request_is_proxied_and_streamed(proxy_client, runtime_configured):
    _login(proxy_client, "admin-1", ["admin"])
    resp = proxy_client.post(
        "/copilotkit",
        json={"query": "{ hello }"},
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"data": {"hello": "world"}}
    assert _RECORDS["method"] == "POST"
    assert _RECORDS["url"] == "http://runtime.test:3111/copilotkit"
    assert '"query"' in _RECORDS["body"]


def test_subpath_is_forwarded(proxy_client, runtime_configured):
    _login(proxy_client, "admin-1", ["admin"])
    resp = proxy_client.get("/copilotkit/some/asset")
    assert resp.status_code == 200
    assert _RECORDS["url"] == "http://runtime.test:3111/copilotkit/some/asset"


def test_workbench_credentials_are_stripped(proxy_client, runtime_configured):
    _login(proxy_client, "admin-1", ["admin"])
    proxy_client.post(
        "/copilotkit",
        json={},
        headers={"content-type": "application/json"},
    )
    forwarded = {k.lower() for k in _RECORDS["headers"]}
    # The workbench's own credentials must not leak to the runtime; host /
    # content-length are re-set by httpx from the upstream URL and body.
    assert "cookie" not in forwarded
    assert "authorization" not in forwarded
    assert "x-api-key" not in forwarded
    assert _RECORDS["headers"].get("content-type") == "application/json"


def test_upstream_outage_is_502(proxy_client, monkeypatch):
    monkeypatch.setattr(copilot_routes, "COPILOT_RUNTIME_URL", "http://runtime.test:3111")

    def _boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(
        copilot_routes,
        "_build_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(_boom), timeout=copilot_routes._TIMEOUT
        ),
    )
    _login(proxy_client, "admin-1", ["admin"])
    resp = proxy_client.post("/copilotkit", json={})
    assert resp.status_code == 502
    assert "unreachable" in resp.json()["error"]


# --- island rendering (base.html include) ----------------------------------- #


def _get_page(client: TestClient) -> str:
    resp = client.get("/rubrics")
    assert resp.status_code == 200
    return resp.text


def test_admin_sees_the_island_when_runtime_configured(proxy_client, monkeypatch):
    # templating.py binds the setting by value at import time, so patch its
    # module attribute rather than copilot_routes'.
    monkeypatch.setattr(
        "src.web.templating.COPILOT_RUNTIME_URL", "http://runtime.test:3111"
    )
    _login(proxy_client, "admin-1", ["admin"])
    html = _get_page(proxy_client)
    assert 'id="lawbench-assistant-root"' in html
    assert "assistant/assistant.js" in html
    assert "assistant/style.css" in html


def test_non_admin_page_has_no_island_markup(proxy_client, monkeypatch):
    monkeypatch.setattr(
        "src.web.templating.COPILOT_RUNTIME_URL", "http://runtime.test:3111"
    )
    _login(proxy_client, "viewer-1", ["content:read"])
    html = _get_page(proxy_client)
    assert "lawbench-assistant-root" not in html
    assert "assistant/assistant.js" not in html


def test_island_hidden_when_runtime_unconfigured(proxy_client, monkeypatch):
    monkeypatch.setattr("src.web.templating.COPILOT_RUNTIME_URL", "")
    _login(proxy_client, "admin-1", ["admin"])
    html = _get_page(proxy_client)
    assert "lawbench-assistant-root" not in html
