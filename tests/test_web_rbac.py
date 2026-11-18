"""RBAC tests for the web workbench (change ``add-web-rbac-and-login-ui``).

Exercises the REAL ``get_current_user`` + ``require_scope`` — no dependency
override — so scope resolution on every credential channel, per-route gating
(401 vs 403 vs the handler's own 404), and the login admission gate are actually
under test.

No IdP / LLM / network is hit: ``logto.verify_reachable`` is neutralized so
``create_app()``'s fail-closed startup probe doesn't fire, and the Logto token
functions are monkeypatched per-test. API keys use the real ``apikey`` module
against the seeded DB (real hash/verify), like ``test_web_auth.py``.

Covers Tasks 2.6 (channel scope resolution), 3.4 (admission gate), and 4.4
(per-route scope enforcement).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.settings import AUTH_COOKIE_NAME
from src.web.app import create_app
from src.web.auth import apikey, logto, session
from src.web.auth.scopes import scopes_from_claims
from src.web.deps import get_db
from src.web.routes import auth as auth_routes


@pytest.fixture
def rbac_client(seeded_db, monkeypatch) -> TestClient:
    """A TestClient with the REAL ``get_current_user`` (auth NOT bypassed)."""
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: seeded_db
    with TestClient(app) as client:
        yield client


# --- helpers --------------------------------------------------------------- #

# A valid body for the rubric PATCH routes. A valid body keeps the test
# insensitive to FastAPI's dependency-vs-validation ordering: the 403 (scope)
# or the handler's 404 (missing rubric) is what surfaces, never a 422.
_PATCH_BODY = {"name": "x", "context": "contract", "description": None}

# The permission-scope vocabulary the API Resource defines.
_ADMIN = ["admin"]
_EDITOR = ["content:read", "content:write"]
_VIEWER = ["content:read"]


def _cookie(payload: dict) -> str:
    """Mint a validly-signed session cookie value for ``payload``."""
    return session._serializer().dumps(session._normalize(payload))


def _set_cookie(client: TestClient, sub: str, scopes: list[str]) -> None:
    """Set a session cookie carrying ``scopes``.

    The scopes are run through the real normalizer (``admin`` -> ``"*"``) so the
    cookie mirrors what ``/auth/callback`` persists.
    """
    normalized = scopes_from_claims({"scope": " ".join(scopes)})
    client.cookies.set(AUTH_COOKIE_NAME, _cookie({"sub": sub, "scopes": normalized}))


def _bearer_headers(monkeypatch, scopes: list[str], sub: str = "bearer-user") -> dict:
    """Patch ``validate_jwt`` to return access-token claims carrying ``scopes``."""
    monkeypatch.setattr(
        logto,
        "validate_jwt",
        lambda token: {
            "sub": sub,
            "name": "Bearer User",
            "email": "bearer@example.com",
            "scope": " ".join(scopes),
        },
    )
    return {"Authorization": "Bearer test-token"}


def _patch_idp(monkeypatch, claims: dict) -> None:
    """Patch the whole Logto callback chain to succeed with fixed ``claims``.

    The ``claims`` dict doubles as the access-token claims, so its ``scope`` key
    drives the admission gate and the persisted session scopes.
    """
    monkeypatch.setattr(
        logto,
        "build_authorize_url",
        lambda state, code_challenge, redirect_uri: "http://test-logto.local/authorize",
    )
    monkeypatch.setattr(
        logto,
        "exchange_code",
        lambda code, code_verifier, redirect_uri: {
            "id_token": "id-token",
            "access_token": "access-token",
        },
    )
    monkeypatch.setattr(logto, "validate_id_token", lambda id_token: claims)
    monkeypatch.setattr(logto, "validate_jwt", lambda access_token: claims)
    monkeypatch.setattr(logto, "fetch_userinfo", lambda access_token: {})


def _begin_login(client: TestClient) -> str:
    """GET ``/auth/login`` (no follow) and return the state from the PKCE cookie.

    Requires ``logto.build_authorize_url`` to be patched first. The PKCE cookie
    is stored in the client jar, so the subsequent ``/auth/callback`` request
    carries it automatically.
    """
    r = client.get("/auth/login", follow_redirects=False)
    assert r.status_code == 302
    token = r.cookies.get("lawbench_pkce")
    assert token  # the redirect must carry the signed PKCE state carrier
    payload = auth_routes._pkce_serializer().loads(token, max_age=600)
    return payload["s"]


def _callback(client: TestClient, state: str):
    return client.get(
        f"/auth/callback?code=abc&state={state}", follow_redirects=False
    )


# --- Task 2.6: channel scope resolution ------------------------------------ #

# The routes chosen below distinguish authorization from "not found":
#   PATCH  /api/rubrics/{name}  requires content:write -> handler 404 if allowed
#   DELETE /api/rubrics/{name}  requires admin         -> handler 404 if allowed
# So a 403 proves the scope check failed; a 404 proves it passed and the
# handler ran (the rubric name does not exist in the seed).


def test_cookie_editor_resolves_content_write(rbac_client: TestClient):
    """Cookie channel: content:write in the session scopes passes the write gate."""
    _set_cookie(rbac_client, "c-editor", _EDITOR)
    r = rbac_client.patch("/api/rubrics/nope", json=_PATCH_BODY)
    assert r.status_code == 404  # scope passed -> handler ran -> not found


def test_cookie_viewer_lacks_content_write(rbac_client: TestClient):
    """Cookie channel: content:read only -> 403 on a write route."""
    _set_cookie(rbac_client, "c-viewer", _VIEWER)
    r = rbac_client.patch("/api/rubrics/nope", json=_PATCH_BODY)
    assert r.status_code == 403
    assert r.json()["detail"] == "missing scope: content:write"


def test_cookie_admin_wildcard_passes_admin_route(rbac_client: TestClient):
    """Cookie channel: the ``admin`` permission -> ``"*"`` -> any scope satisfied."""
    _set_cookie(rbac_client, "c-admin", _ADMIN)
    r = rbac_client.delete("/api/rubrics/nope")
    assert r.status_code == 404  # admin scope passed -> handler ran


def test_bearer_editor_resolves_content_write(rbac_client: TestClient, monkeypatch):
    """Bearer channel: scopes parsed from the token's ``scope`` claim."""
    headers = _bearer_headers(monkeypatch, _EDITOR)
    r = rbac_client.patch("/api/rubrics/nope", json=_PATCH_BODY, headers=headers)
    assert r.status_code == 404


def test_bearer_viewer_lacks_content_write(rbac_client: TestClient, monkeypatch):
    """Bearer channel: a token without content:write -> 403."""
    headers = _bearer_headers(monkeypatch, _VIEWER)
    r = rbac_client.patch("/api/rubrics/nope", json=_PATCH_BODY, headers=headers)
    assert r.status_code == 403


def test_bearer_unknown_scope_yields_no_access(rbac_client: TestClient, monkeypatch):
    """Bearer channel: an unrecognized scope grants nothing (fail closed)."""
    headers = _bearer_headers(monkeypatch, ["superuser"])
    r = rbac_client.patch("/api/rubrics/nope", json=_PATCH_BODY, headers=headers)
    assert r.status_code == 403


def test_api_key_channel_uses_stored_scopes(rbac_client: TestClient):
    """API-key channel: authorization uses the key's STORED scopes."""
    plaintext = apikey.create_key("api-user", "writer", ["content:write"])
    r = rbac_client.patch(
        "/api/rubrics/nope", json=_PATCH_BODY, headers={"X-API-Key": plaintext}
    )
    assert r.status_code == 404  # stored content:write -> handler ran


def test_api_key_without_scope_is_403(rbac_client: TestClient):
    """API-key channel: a key whose stored scopes lack the required scope -> 403."""
    plaintext = apikey.create_key("api-user", "reader", ["content:read"])
    r = rbac_client.patch(
        "/api/rubrics/nope", json=_PATCH_BODY, headers={"X-API-Key": plaintext}
    )
    assert r.status_code == 403


# --- Task 4.4: per-route enforcement (401 vs 403 vs admin) ----------------- #


def test_no_credential_is_401_on_write_route(rbac_client: TestClient):
    """No credential at all -> 401 (unauthenticated), never 403."""
    r = rbac_client.patch("/api/rubrics/nope", json=_PATCH_BODY)
    assert r.status_code == 401


def test_admin_route_rejects_editor(rbac_client: TestClient):
    """Editor may write but not delete: DELETE requires admin -> 403."""
    _set_cookie(rbac_client, "e", _EDITOR)
    r = rbac_client.delete("/api/rubrics/nope")
    assert r.status_code == 403
    assert r.json()["detail"] == "missing scope: admin"


def test_admin_route_rejects_viewer(rbac_client: TestClient):
    """Viewer -> 403 on the admin-only DELETE."""
    _set_cookie(rbac_client, "v", _VIEWER)
    assert rbac_client.delete("/api/rubrics/nope").status_code == 403


def test_admin_route_allows_admin(rbac_client: TestClient):
    """Admin -> passes the admin gate; the handler then 404s (no such rubric)."""
    _set_cookie(rbac_client, "a", _ADMIN)
    assert rbac_client.delete("/api/rubrics/nope").status_code == 404


def test_viewer_can_read(rbac_client: TestClient):
    """Read routes are ungated: a viewer may list rubrics (200)."""
    _set_cookie(rbac_client, "v", _VIEWER)
    assert rbac_client.get("/api/rubrics").status_code == 200


def test_content_write_route_rejects_viewer_and_allows_editor(
    rbac_client: TestClient,
):
    """The same content:write route is 403 for viewer, 404 (ran) for editor."""
    _set_cookie(rbac_client, "v", _VIEWER)
    assert rbac_client.patch("/api/rubrics/nope", json=_PATCH_BODY).status_code == 403
    _set_cookie(rbac_client, "e", _EDITOR)
    assert rbac_client.patch("/api/rubrics/nope", json=_PATCH_BODY).status_code == 404


# --- Task 3.4: login admission gate ---------------------------------------- #


def test_callback_admits_identity_with_admitted_scope(
    rbac_client: TestClient, monkeypatch
):
    """An identity holding an admitted permission gets a session + redirect."""
    _patch_idp(
        monkeypatch,
        {"sub": "u1", "email": "a@b.c", "scope": "content:read content:write"},
    )
    r = _callback(rbac_client, _begin_login(rbac_client))
    assert r.status_code == 302
    assert r.cookies.get(AUTH_COOKIE_NAME)  # session established


def test_callback_denies_scopeless_identity(rbac_client: TestClient, monkeypatch):
    """An authenticated identity with NO permission scope is refused (403)."""
    _patch_idp(monkeypatch, {"sub": "u2", "email": "b@c.d", "scope": ""})
    r = _callback(rbac_client, _begin_login(rbac_client))
    assert r.status_code == 403
    assert r.cookies.get(AUTH_COOKIE_NAME) is None


def test_callback_denies_missing_scope_claim(rbac_client: TestClient, monkeypatch):
    """A token without the scope claim at all is denied (fail closed)."""
    _patch_idp(monkeypatch, {"sub": "u3", "email": "c@d.e"})  # no "scope" key
    r = _callback(rbac_client, _begin_login(rbac_client))
    assert r.status_code == 403
    assert r.cookies.get(AUTH_COOKIE_NAME) is None


def test_callback_denies_unknown_scope(rbac_client: TestClient, monkeypatch):
    """A scope outside the admitted set is denied."""
    _patch_idp(monkeypatch, {"sub": "u4", "email": "d@e.f", "scope": "contractor"})
    r = _callback(rbac_client, _begin_login(rbac_client))
    assert r.status_code == 403
    assert r.cookies.get(AUTH_COOKIE_NAME) is None


def test_callback_warn_mode_admits_scopeless(
    rbac_client: TestClient, monkeypatch, caplog
):
    """``AUTH_ADMISSION_MODE=warn`` logs the denial and admits anyway (staged rollout)."""
    monkeypatch.setenv("AUTH_ADMISSION_MODE", "warn")
    _patch_idp(monkeypatch, {"sub": "u5", "email": "e@f.g", "scope": ""})
    state = _begin_login(rbac_client)
    with caplog.at_level("WARNING", logger="src.web.routes.auth"):
        r = _callback(rbac_client, state)
    assert r.status_code == 302
    assert r.cookies.get(AUTH_COOKIE_NAME)
    assert any("admission gate" in rec.message for rec in caplog.records)
