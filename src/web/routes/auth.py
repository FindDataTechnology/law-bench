"""Auth routes: OIDC login/callback/logout + API-key management.

Browser login is the OIDC authorization-code flow with PKCE S256::

    GET /auth/login     -> 302 to Logto /authorize (state + code_challenge)
    GET /auth/callback  -> exchange code for tokens, validate the id_token
                           (identity) AND the access_token (permission scopes),
                           set signed session cookie, 302 to the ``next``
                           path (or ``/``). 400 on invalid/expired state
                           or a failed exchange.
    GET /auth/logout    -> clear session cookie, 302 to Logto end-session
                           (or ``/`` if the IdP has no end-session endpoint).

A short-lived signed cookie (``lawbench_pkce``) ferries the PKCE
``code_verifier`` + ``state`` + ``next`` across the IdP redirect — the app is
otherwise stateless (no server-side session store). The cookie is single-use:
the callback deletes it. Its signature is keyed by the same
``AUTH_SESSION_SECRET`` as the session cookie but namespaced by a distinct
salt so the two signing contexts can't be confused.

API-key management (the programmatic channel's self-service surface)::

    POST   /api/keys         -> create, return plaintext ONCE (201)
    GET    /api/keys         -> list the caller's keys (never the hash)
    DELETE /api/keys/{id}    -> revoke; 404 if not the owner (not 403 —
                               leaking key existence is worse than a
                               clean miss)

``/auth/*`` are exempt from the constructor-level auth dependency (Task 8.1)
so the login flow is reachable pre-authentication; ``/api/keys`` is protected
via ``Depends(get_current_user)`` on each handler (and later by the
constructor-level dep too — FastAPI caches the resolved user per request, so
declaring it again is free).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from src.settings import (
    APP_BASE_URL,
    AUTH_COOKIE_SECURE,
    AUTH_SESSION_SECRET,
    LOGTO_REDIRECT_URI,
    ConfigError,
    admission_mode,
)

from ..auth import apikey, logto, session
from ..auth.deps import User, get_current_user
from ..auth.scopes import is_admitted, scopes_from_claims
from ..models import ApiKeyCreate, ApiKeyCreated, ApiKeyOut
from ..templating import templates as _templates

router = APIRouter(tags=["auth"])

_log = logging.getLogger(__name__)


# --- PKCE + state cookie (single-use, signed, short-lived) ------------------ #
#
# The verifier + state must survive the IdP redirect round-trip. With no
# server-side session store, a signed short-lived cookie is the standard
# stateless carrier. ``AUTH_SESSION_SECRET`` keys it (same secret, different
# salt -> domain separation); the callback deletes the cookie so it can't be
# replayed.

_PKCE_COOKIE = "lawbench_pkce"
_PKCE_SALT = "lawbench-pkce-v1"
_PKCE_TTL = 600  # 10 min — a login must complete fast; a stale challenge = retry.


def _pkce_serializer() -> URLSafeTimedSerializer:
    if not AUTH_SESSION_SECRET:
        raise ConfigError(
            "AUTH_SESSION_SECRET is not set — refusing to sign PKCE cookie."
        )
    return URLSafeTimedSerializer(AUTH_SESSION_SECRET, salt=_PKCE_SALT)


def _make_pkce_pair() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` for PKCE S256."""
    verifier = secrets.token_urlsafe(64)  # ~85 urlsafe chars (within 43..128)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _set_pkce_cookie(
    response: RedirectResponse, verifier: str, state: str, next_url: str
) -> None:
    token = _pkce_serializer().dumps({"v": verifier, "s": state, "n": next_url})
    response.set_cookie(
        _PKCE_COOKIE,
        token,
        max_age=_PKCE_TTL,
        httponly=True,
        secure=AUTH_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def _get_pkce_cookie(request: Request) -> dict[str, str] | None:
    token = request.cookies.get(_PKCE_COOKIE)
    if not token:
        return None
    try:
        payload = _pkce_serializer().loads(token, max_age=_PKCE_TTL)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(payload, dict):
        return None
    return payload  # type: ignore[return-value]


def _clear_pkce_cookie(response: RedirectResponse) -> None:
    response.delete_cookie(_PKCE_COOKIE, path="/")


# --- helpers --------------------------------------------------------------- #


def _safe_next(path: str | None) -> str:
    """Whitelist a post-login redirect target to defeat open-redirect.

    Only same-origin absolute paths (``/...``) are allowed; ``//host`` (a
    protocol-relative URL) and anything else falls back to ``/``.
    """
    if not path or not path.startswith("/") or path.startswith("//"):
        return "/"
    return path


def _post_logout_uri() -> str | None:
    """Post-logout redirect target: ``APP_BASE_URL`` + ``/`` (or ``None``).

    Logto must register this URL as a post-logout redirect URI (a deploy concern,
    Task 10.3). When ``APP_BASE_URL`` is unset, ``None`` is returned so the IdP
    end-session endpoint is still hit (without a redirect target) — the IdP then
    shows its own post-logout page, and the local session cookie is cleared
    regardless.
    """
    if not APP_BASE_URL:
        return None
    return f"{APP_BASE_URL.rstrip('/')}/"


# --- OIDC login / callback / logout ---------------------------------------- #


@router.get("/auth/login", include_in_schema=False)
def login(next: str = "/") -> RedirectResponse:
    """Start the OIDC authorization-code flow: 302 to Logto /authorize.

    Generates a PKCE verifier + challenge and a random ``state`` (CSRF token),
    ferries them in a signed short-lived cookie, and redirects to the IdP
    authorize endpoint. ``next`` is the post-login path (validated same-origin
    in the callback to defeat open-redirect).
    """
    verifier, challenge = _make_pkce_pair()
    state = secrets.token_urlsafe(32)
    try:
        authorize_url = logto.build_authorize_url(
            state=state,
            code_challenge=challenge,
            redirect_uri=LOGTO_REDIRECT_URI,
        )
    except logto.LogtoUnreachable as exc:
        raise HTTPException(503, "IdP unreachable — cannot start login") from exc
    except logto.LogtoError as exc:
        raise HTTPException(500, f"login misconfigured: {exc}") from exc

    response = RedirectResponse(url=authorize_url, status_code=302)
    _set_pkce_cookie(response, verifier, state, _safe_next(next))
    return response


@router.get("/auth/callback", include_in_schema=False)
def callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    error_description: str = "",
) -> Response:
    """Complete the OIDC flow: exchange code, validate tokens, set cookie.

    400 on a missing/expired PKCE cookie, a state mismatch (CSRF), or a failed
    token exchange. 503 if the IdP is unreachable mid-flow. 401 if the id_token
    or access_token fails validation. 403 (login-denied page, no session
    cookie) if the identity holds no admitted permission scope. On success: 302
    to the ``next`` path with a fresh session cookie; the PKCE cookie is deleted
    (single-use).
    """
    # The IdP may return an error inline (e.g. user denied consent / access_denied).
    if error:
        raise HTTPException(
            400, f"IdP returned error: {error} — {error_description}"
        )

    pkce = _get_pkce_cookie(request)
    if pkce is None:
        raise HTTPException(400, "missing or expired login state — retry /auth/login")
    if not code or not state:
        raise HTTPException(400, "missing code or state")
    # Constant-time compare — state is a CSRF token.
    if not hmac.compare_digest(state, pkce.get("s", "")):
        raise HTTPException(400, "state mismatch — possible CSRF")

    try:
        tokens = logto.exchange_code(code, pkce["v"], LOGTO_REDIRECT_URI)
    except logto.LogtoUnreachable as exc:
        raise HTTPException(503, "IdP unreachable during token exchange") from exc
    except logto.LogtoError as exc:
        raise HTTPException(400, f"token exchange failed: {exc}") from exc

    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(400, "no id_token in token response")

    try:
        claims = logto.validate_id_token(id_token)
    except logto.InvalidToken as exc:
        raise HTTPException(401, "invalid id_token") from exc
    except logto.LogtoUnreachable as exc:
        raise HTTPException(503, "IdP unreachable during id_token validation") from exc

    # The access token is minted for the configured API Resource; its ``scope``
    # claim is the user's granted permission subset — the authorization truth.
    # The id_token above proves *identity*; this proves *authorization*.
    access_token = tokens.get("access_token", "")
    if not access_token:
        raise HTTPException(400, "no access_token in token response")
    try:
        access_claims = logto.validate_jwt(access_token)
    except logto.InvalidToken as exc:
        raise HTTPException(401, "invalid access_token") from exc
    except logto.LogtoUnreachable as exc:
        raise HTTPException(
            503, "IdP unreachable during access_token validation"
        ) from exc

    granted_scopes = scopes_from_claims(access_claims)

    # Best-effort profile enrichment (access_token -> userinfo). A failure here
    # must not break login — the id_token already carries sub/name/email.
    try:
        userinfo = logto.fetch_userinfo(access_token)
    except logto.LogtoError:
        userinfo = {}

    # Admission gate (fail closed). An identity that authenticates but holds no
    # admitted permission scope is NOT given a session. ``warn`` mode logs the
    # granted scopes and admits anyway so the Logto permissions can be verified
    # during a staged rollout without locking everyone out.
    if not is_admitted(granted_scopes):
        if admission_mode() == "warn":
            _log.warning(
                "admission gate (warn): sub=%s scopes=%s not admitted — admitting",
                claims.get("sub", ""),
                granted_scopes,
            )
        else:
            _log.info(
                "login denied: sub=%s scopes=%s (no admitted scope)",
                claims.get("sub", ""),
                granted_scopes,
            )
            denied = _templates.TemplateResponse(
                request,
                "login_denied.html",
                {"email": str(claims.get("email") or userinfo.get("email") or "")},
                status_code=403,
            )
            _clear_pkce_cookie(denied)
            return denied

    payload = {
        "sub": str(claims.get("sub", "")),
        "name": str(claims.get("name") or userinfo.get("name") or ""),
        "email": str(
            claims.get("email")
            or userinfo.get("email")
            or claims.get("preferred_username")
            or ""
        ),
        "scopes": granted_scopes,
    }

    next_url = _safe_next(pkce.get("n", "/"))
    response = RedirectResponse(url=next_url, status_code=302)
    session.set_session(response, payload)
    _clear_pkce_cookie(response)
    return response


@router.get("/auth/logout", include_in_schema=False)
def logout() -> RedirectResponse:
    """Clear the session cookie and redirect to the IdP end-session endpoint.

    If Logto advertises no end-session endpoint, redirect to ``/`` (the local
    session is cleared either way). The IdP session is ended best-effort; we
    pass no ``id_token_hint`` (the id_token isn't kept in the session cookie,
    only the resolved identity is) — ``end_session_url`` supplies ``client_id``
    instead so Logto honours the post-logout redirect.
    """
    try:
        end = logto.end_session_url(
            id_token_hint=None,
            post_logout_redirect_uri=_post_logout_uri(),
        )
    except logto.LogtoError:
        end = None
    target = end or "/"
    response = RedirectResponse(url=target, status_code=302)
    session.clear_session(response)
    return response


# --- API-key self-service -------------------------------------------------- #


@router.post("/api/keys", status_code=201, response_model=ApiKeyCreated)
def create_api_key(
    body: ApiKeyCreate, user: User = Depends(get_current_user)
) -> dict:
    """Create a new API key for the current user; return the plaintext ONCE.

    The plaintext is shown here and never retrievable again — only the public
    prefix + salted hash are persisted. The response carries the plaintext plus
    what was requested; the full row (with id) is available via ``GET /api/keys``.
    """
    plaintext = apikey.create_key(user.sub, body.label, body.scopes)
    return {
        "key": plaintext,
        "label": body.label,
        "scopes": list(body.scopes),
    }


@router.get("/api/keys", response_model=list[ApiKeyOut])
def list_api_keys(user: User = Depends(get_current_user)) -> list[dict]:
    """List the current user's API keys (never the hash, never the plaintext)."""
    return apikey.list_keys(user.sub)


@router.delete("/api/keys/{key_id}", status_code=204)
def revoke_api_key(key_id: int, user: User = Depends(get_current_user)) -> None:
    """Revoke (soft-delete) an API key.

    A non-existent id or a key owned by another user both return 404 — the
    response does not leak that the key exists (404, not 403). Idempotent:
    revoking an already-revoked own key still succeeds.
    """
    if not apikey.revoke_key(key_id, user.sub):
        raise HTTPException(404, "key not found")
    return None
