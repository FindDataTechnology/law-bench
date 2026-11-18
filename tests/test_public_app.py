"""Tests for the public read-only API app factory (``create_public_app``).

These exercise the REAL ``get_current_user`` — no dependency override — so the
key-only posture is actually under test: an unauthenticated caller gets 401, a
valid ``X-API-Key`` gets 200, and the excluded write/admin routes are absent
(404, not 401 — a 401 would mean the route is present-but-protected; 404 proves
it is not mounted). The docs surface is locked down (``/openapi.json`` 404) and
``/healthz`` stays open unauthenticated.

The Logto IdP is never hit: the public factory's startup calls
``check_public_auth_config()`` (no ``verify_reachable``), and no test presents a
Bearer, so ``validate_jwt`` is never called. API keys use the real ``apikey``
module against the seeded DB (real hash/verify).

Covers OpenSpec task 1.4 (public app assertions) and 7.1 (auth/key routes absent).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.web.auth import apikey
from src.web.deps import get_db
from src.web.public_app import create_public_app


@pytest.fixture
def public_client(seeded_db) -> TestClient:
    """A TestClient for the public app with the REAL ``get_current_user``.

    Auth is NOT bypassed (no override of ``get_current_user``) so the key-only
    posture is under test. ``get_db`` is overridden to the seeded DB so route
    handlers read the throwaway DB; API-key verify resolves ``DEFAULT_DB`` ->
    the same env DSN (set by ``seeded_db``). The public factory's startup runs
    ``check_public_auth_config()`` (no Logto reachability probe), so it boots
    without any IdP monkeypatch — proving the China-box posture.
    """
    app = create_public_app()
    app.dependency_overrides[get_db] = lambda: seeded_db
    with TestClient(app) as client:
        yield client


# --- (d) /healthz is 200 unauthenticated ----------------------------------- #


def test_healthz_open_without_creds(public_client: TestClient):
    """``/healthz`` is exempt — 200 with no credential (task 1.4d)."""
    r = public_client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# --- (c) docs surface locked down (404) ------------------------------------ #


def test_openapi_json_is_404(public_client: TestClient):
    """``/openapi.json`` is not registered — docs locked down (task 1.4c)."""
    r = public_client.get("/openapi.json")
    assert r.status_code == 404


def test_swagger_docs_is_404(public_client: TestClient):
    """``/api/docs`` (Swagger UI) is not registered either."""
    r = public_client.get("/api/docs")
    assert r.status_code == 404


def test_redoc_is_404(public_client: TestClient):
    """``/redoc`` is not registered either."""
    r = public_client.get("/redoc")
    assert r.status_code == 404


# --- (a) 401 without a key, 200 with a valid key --------------------------- #


def test_read_route_401_without_creds(public_client: TestClient):
    """No cookie, no Bearer, no API key -> 401 on a public read route (task 1.4a)."""
    r = public_client.get("/api/contracts/sale")
    assert r.status_code == 401


def test_read_route_200_with_valid_api_key(public_client: TestClient):
    """A real X-API-Key authenticates on the public read route (task 1.4a)."""
    plaintext = apikey.create_key("api-user", "public-test", ["*"])
    r = public_client.get("/api/contracts/sale", headers={"X-API-Key": plaintext})
    assert r.status_code == 200


# --- (b) write/admin routes are NOT registered (404, not 401) -------------- #


def test_keys_route_not_registered(public_client: TestClient):
    """``/api/keys`` (key issuance) is on the excluded ``auth`` router -> 404, not
    401. A 401 would mean the route is present but protected; 404 proves it is
    absent (task 1.4b / 7.1). Key management stays on the origin only.
    """
    r = public_client.get("/api/keys")
    assert r.status_code == 404
    r = public_client.post("/api/keys", json={"label": "x", "scopes": ["read"]})
    assert r.status_code == 404


def test_auth_login_not_registered(public_client: TestClient):
    """``/auth/login`` (OIDC) is on the excluded ``auth`` router -> 404, not 302.
    The public pod has no browser login flow (task 7.1)."""
    r = public_client.get("/auth/login", follow_redirects=False)
    assert r.status_code == 404


def test_generate_write_route_not_registered(public_client: TestClient):
    """``POST /api/contracts/sale/generate`` is on the excluded ``write_router``
    -> 404, not 401. The public pod mounts only ``read_only_router`` for
    ``contract_context`` (task 1.4b). Generation stays on the origin.
    """
    r = public_client.post("/api/contracts/sale/generate", json={"format": "markdown"})
    assert r.status_code == 404


def test_generate_stored_write_route_not_registered(public_client: TestClient):
    """``POST /api/contracts/sale/generate-stored`` is also on the excluded
    ``write_router`` -> 404."""
    r = public_client.post("/api/contracts/sale/generate-stored", json={})
    assert r.status_code == 404


def test_the_fleet_machine_surface_is_not_registered(public_client: TestClient):
    """舰队机器面（工单读 / 认领 / 关单 / 回写运行 / 提交提案 / 读结局）不在公开面上。

    两个理由，任一成立就足够：① 它是**写面**——认领、回写运行、以舰队身份提交产物，
    公开 pod 只该是只读面；② 公开 pod 的库是**复制来的 dump**，`distribution_consumers`
    上根本没有 `kind` / `fleet_ref` 两列（DDL 只在 origin 的 entrypoint 里跑），真把路由
    挂上去，症状会是 500 而不是「用不了」。

    判据是 **404 而不是 401**：401 说明路由在、只是被挡住，那正是要防的形态。
    """
    cases = (
        ("get", "/api/v1/distribution/legal/work-orders", None),
        ("post", "/api/v1/distribution/legal/work-orders/1/claim", None),
        ("post", "/api/v1/distribution/legal/work-orders/1/complete", {}),
        ("post", "/api/v1/distribution/legal/runs", {}),
        ("get", "/api/v1/distribution/legal/runs?runner_ref=fleet:a/p#1", None),
        ("post", "/api/v1/distribution/legal/proposals", {}),
        ("get", "/api/v1/distribution/legal/proposals/outcomes?source=fleet:a/p", None),
    )
    for method, path, body in cases:
        call = getattr(public_client, method)
        response = call(path) if body is None else call(path, json=body)
        assert response.status_code == 404, f"{method.upper()} {path} -> {response.status_code}"
