"""Tests for the Phase 2 hybrid auth (cookie + Bearer + API key).

These exercise the REAL ``get_current_user`` — no dependency override — so the
channel ordering, the present-but-invalid binding rule, and the exempt-path
handling are actually under test. The Logto IdP is never hit:
``logto.verify_reachable`` is neutralized so the fail-closed startup probe
doesn't fire on the test client, and ``logto.validate_jwt`` /
``logto.build_authorize_url`` are monkeypatched per-test so neither JWKS
validation nor the authorize redirect needs a live IdP. API keys use the real
``apikey`` module against the seeded DB (real hash/verify, real revoke).

Covers Task 8.2 (``/healthz`` open), 8.3 (``/auth/login`` 302 not 401), and 9.2.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.settings import AUTH_COOKIE_NAME
from src.web.app import create_app
from src.web.auth import apikey, logto, session
from src.web.deps import get_db
from src.web.routes import auth as auth_routes


@pytest.fixture
def auth_client(seeded_db, monkeypatch) -> TestClient:
    """A TestClient with the REAL ``get_current_user`` (auth NOT bypassed).

    Only the startup IdP probe is neutralized (``verify_reachable`` -> no-op)
    so ``create_app()``'s fail-closed startup doesn't try to reach a real
    Logto. ``logto.validate_jwt`` / ``build_authorize_url`` are patched
    per-test as needed. ``get_db`` is still overridden to the seeded DB so
    route handlers read/write the throwaway DB; API-key CRUD uses the real
    ``apikey`` module which resolves ``DEFAULT_DB`` -> the same env DSN.
    """
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: seeded_db
    with TestClient(app) as client:
        yield client


# --- helpers --------------------------------------------------------------- #


def _bearer_claims(sub: str = "bearer-user") -> dict:
    """Claims a patched validate_jwt returns for any Bearer token."""
    return {
        "sub": sub,
        "name": "Bearer User",
        "email": "bearer@example.com",
        "scope": "openid profile",
    }


def _patch_bearer_ok(monkeypatch, sub: str = "bearer-user") -> None:
    """Make ``logto.validate_jwt`` accept any Bearer, returning fixed claims."""
    monkeypatch.setattr(logto, "validate_jwt", lambda token: _bearer_claims(sub))


def _patch_bearer_invalid(monkeypatch) -> None:
    """Make ``logto.validate_jwt`` reject every Bearer (present-but-invalid)."""

    def _reject(token: str):
        raise logto.InvalidToken("rejected by test stub")

    monkeypatch.setattr(logto, "validate_jwt", _reject)


# Used wherever a request must carry a Bearer the (patched) validate_jwt will
# accept. The token value is irrelevant — _patch_bearer_ok makes validate_jwt
# return fixed claims for ANY input.
_BEARER_HEADERS = {"Authorization": "Bearer test-token"}


def _session_cookie(payload: dict) -> str:
    """Mint a validly-signed session cookie value for ``payload``."""
    return session._serializer().dumps(session._normalize(payload))


# --- exempt paths (Tasks 8.2, 8.3) ----------------------------------------- #


def test_healthz_open_without_creds(auth_client: TestClient):
    """``/healthz`` is exempt — 200 with no credential (Task 8.2)."""
    r = auth_client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_auth_login_returns_302_not_401(auth_client: TestClient, monkeypatch):
    """``/auth/login`` is exempt — 302 to the IdP, never 401 (Task 8.3).

    The constructor-level ``Depends(get_current_user)`` cannot block the login
    flow: ``_EXEMPT_PREFIXES=("/auth/",)`` short-circuits to an anonymous
    sentinel before any credential check.
    """
    monkeypatch.setattr(
        logto,
        "build_authorize_url",
        lambda state, code_challenge, redirect_uri: (
            "http://test-logto.local/authorize?ok=1"
        ),
    )
    r = auth_client.get("/auth/login", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].startswith("http://test-logto.local/authorize")
    # The single-use PKCE state carrier is set on the redirect response.
    assert "lawbench_pkce" in r.cookies


# --- 401 without creds ----------------------------------------------------- #


def test_protected_route_401_without_creds(auth_client: TestClient):
    """No cookie, no Bearer, no API key -> 401 on a protected route."""
    r = auth_client.get("/api/rubrics")
    assert r.status_code == 401


# --- 200 with each valid channel ------------------------------------------- #


def test_protected_route_200_with_valid_cookie(auth_client: TestClient):
    """Strongest channel: a signed session cookie authenticates."""
    auth_client.cookies.set(
        AUTH_COOKIE_NAME,
        _session_cookie(
            {"sub": "cookie-user", "name": "C", "email": "c@e.com", "scopes": ["*"]}
        ),
    )
    r = auth_client.get("/api/rubrics")
    assert r.status_code == 200


def test_protected_route_200_with_valid_bearer(auth_client: TestClient, monkeypatch):
    """Bearer channel: a Logto JWT (validate_jwt patched) authenticates."""
    _patch_bearer_ok(monkeypatch)
    r = auth_client.get("/api/rubrics", headers={"Authorization": "Bearer anything"})
    assert r.status_code == 200


def test_protected_route_200_with_valid_api_key(auth_client: TestClient):
    """API-key channel: a real key (created via the apikey module) authenticates."""
    plaintext = apikey.create_key("api-user", "test-key", ["*"])
    r = auth_client.get("/api/rubrics", headers={"X-API-Key": plaintext})
    assert r.status_code == 200


# --- present-but-invalid is binding (NO fallthrough) ----------------------- #


def test_invalid_bearer_does_not_fall_through_to_api_key(
    auth_client: TestClient, monkeypatch
):
    """A present-but-invalid Bearer binds to 401 — must NOT fall through to a
    valid X-API-Key the same request also carries."""
    _patch_bearer_invalid(monkeypatch)
    plaintext = apikey.create_key("api-user", "k", ["*"])
    r = auth_client.get(
        "/api/rubrics",
        headers={"Authorization": "Bearer bad", "X-API-Key": plaintext},
    )
    assert r.status_code == 401


def test_invalid_cookie_does_not_fall_through_to_api_key(auth_client: TestClient):
    """A present-but-invalid (tampered) session cookie binds to 401 — must NOT
    fall through to a valid X-API-Key. The cookie is the strongest channel, so
    a tampered one rejects the whole request rather than degrading silently."""
    plaintext = apikey.create_key("api-user", "k", ["*"])
    auth_client.cookies.set(AUTH_COOKIE_NAME, "tampered-garbage-value")
    r = auth_client.get("/api/rubrics", headers={"X-API-Key": plaintext})
    assert r.status_code == 401


def test_invalid_api_key_is_401(auth_client: TestClient):
    """A present-but-invalid X-API-Key (wrong format / unknown prefix) -> 401;
    no weaker channel remains to fall through to."""
    r = auth_client.get("/api/rubrics", headers={"X-API-Key": "lbk_not-a-real-key"})
    assert r.status_code == 401


# --- API-key management lifecycle (create / list / revoke) ----------------- #


def test_api_key_lifecycle_create_list_revoke(auth_client: TestClient, monkeypatch):
    """Full self-service lifecycle over HTTP (Bearer-auth'd as the owner)."""
    _patch_bearer_ok(monkeypatch, sub="owner")

    # Every call here authenticates via the (patched) Bearer channel —
    # _patch_bearer_ok makes validate_jwt return fixed claims for ANY token,
    # so the literal value is irrelevant, but the Authorization header must be
    # PRESENT or get_current_user never reaches the Bearer branch (it would 401
    # on "no credential" before validate_jwt is ever called).
    H = _BEARER_HEADERS

    # create -> plaintext returned ONCE
    r = auth_client.post("/api/keys", json={"label": "ci", "scopes": ["read"]}, headers=H)
    assert r.status_code == 201
    body = r.json()
    assert body["label"] == "ci"
    assert body["scopes"] == ["read"]
    plaintext = body["key"]
    assert plaintext.startswith("lbk_")

    # list -> one key, never the hash, id + prefix visible
    r = auth_client.get("/api/keys", headers=H)
    assert r.status_code == 200
    keys = r.json()
    assert len(keys) == 1
    row = keys[0]
    key_id = row["id"]
    assert row["key_prefix"] == plaintext[:16]
    assert row["label"] == "ci"
    assert "key_hash" not in row  # the hash is never exposed
    assert row["revoked_at"] is None

    # revoke -> 204
    r = auth_client.delete(f"/api/keys/{key_id}", headers=H)
    assert r.status_code == 204

    # list again -> still present, now revoked
    r = auth_client.get("/api/keys", headers=H)
    assert r.json()[0]["revoked_at"] is not None

    # the revoked plaintext no longer authenticates (verify_key filters revoked).
    # This request uses the API-key channel, so NO Bearer — prove the revoked
    # key itself is rejected, not that a missing Bearer is.
    r = auth_client.get("/api/rubrics", headers={"X-API-Key": plaintext})
    assert r.status_code == 401


# --- cross-user revoke returns 404 (not 403) ------------------------------- #


def test_cross_user_revoke_returns_404(auth_client: TestClient, monkeypatch):
    """Revoking another user's key -> 404, not 403 (no existence leak), and the
    key remains valid for its real owner."""
    # owner A creates a key directly (not via HTTP, so Bearer sub is irrelevant)
    plaintext = apikey.create_key("user-a", "a-key", ["*"])
    key_id = apikey.list_keys("user-a")[0]["id"]

    # user B (different sub) attempts to revoke A's key over HTTP. The DELETE
    # must carry a Bearer or get_current_user 401s on "no credential" before the
    # revoke logic (and the patched validate_jwt) is reached.
    _patch_bearer_ok(monkeypatch, sub="user-b")
    r = auth_client.delete(f"/api/keys/{key_id}", headers=_BEARER_HEADERS)
    assert r.status_code == 404

    # the key was NOT revoked by B — it still authenticates as user-a
    r = auth_client.get("/api/rubrics", headers={"X-API-Key": plaintext})
    assert r.status_code == 200


# --- logout: end-session URL must name the client -------------------------- #


def _patch_end_session(monkeypatch) -> None:
    monkeypatch.setattr(
        logto,
        "fetch_discovery",
        lambda: {"end_session_endpoint": "https://idp.test/oidc/session/end"},
    )
    monkeypatch.setattr(logto, "LOGTO_CLIENT_ID", "test-client-id")


def test_end_session_url_includes_client_id(monkeypatch):
    """``end_session_url`` must send ``client_id``.

    Logto's upstream (node-oidc-provider) resolves the client from
    ``id_token_hint`` or ``client_id``; with neither it **silently drops**
    ``post_logout_redirect_uri``, so the user lands on the generic end-session
    success page instead of back in the app. Regression for that observed bug.
    """
    _patch_end_session(monkeypatch)
    url = logto.end_session_url(
        id_token_hint=None, post_logout_redirect_uri="https://app.test/"
    )
    assert url is not None
    assert "client_id=test-client-id" in url
    assert "post_logout_redirect_uri=https%3A%2F%2Fapp.test%2F" in url


def test_logout_redirects_to_end_session_with_client_id(
    auth_client: TestClient, monkeypatch
):
    """``/auth/logout`` -> 302 to the IdP end-session URL carrying our client.

    Regression: without ``client_id`` Logto ignores ``post_logout_redirect_uri``
    and the user never returns to the app after signing out.
    """
    _patch_end_session(monkeypatch)
    monkeypatch.setattr(auth_routes, "APP_BASE_URL", "https://app.test")
    cookie = _session_cookie(
        {"sub": "u1", "name": "U", "email": "u@test", "scopes": ["content:read"]}
    )
    auth_client.cookies.set(AUTH_COOKIE_NAME, cookie)
    r = auth_client.get("/auth/logout", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("https://idp.test/oidc/session/end?")
    assert "client_id=test-client-id" in loc
    assert "post_logout_redirect_uri=https%3A%2F%2Fapp.test%2F" in loc
    # the local session cookie is cleared on the way out
    assert AUTH_COOKIE_NAME in r.headers.get("set-cookie", "")
