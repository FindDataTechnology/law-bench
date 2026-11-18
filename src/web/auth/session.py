"""Signed session cookie for browser sessions (Phase 2 auth).

The browser channel authenticates via the OIDC authorization-code flow: Logto
issues id/access tokens at ``/auth/callback``; this module persists the
*resolved* identity (``sub``/``name``/``email``/``scopes``) into a signed,
timestamped cookie so subsequent requests don't re-hit the IdP. The cookie's
signature is the trust root — the JWT is validated once at callback time, then
the signed cookie stands for the session lifetime. The resolved permission
``scopes`` are persisted verbatim; authorization checks them directly, so a
stale or tampered cookie cannot widen access beyond the scopes it carries.

Cookie attributes are fixed to the security-required set:
- ``httpOnly=True`` — no JS access (defeats token exfil via XSS),
- ``SameSite=Lax`` — CSRF resistance for top-level navigations,
- ``Secure`` — governed by ``AUTH_COOKIE_SECURE`` (off only for localhost dev;
  httpOnly + SameSite=Lax remain on regardless),
- ``max_age`` = ``AUTH_SESSION_TTL`` (default 7d); the serializer also enforces
  it cryptographically via the embedded timestamp, so a tampered/stale cookie
  is rejected even if a client ignores ``max_age``.

Signing uses :class:`itsdangerous.URLSafeTimedSerializer` keyed by the stable
deploy secret ``AUTH_SESSION_SECRET`` (never auto-generated per restart). The
salt namespaces the signature so the same secret isn't reused across signing
contexts.
"""

from __future__ import annotations

from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from starlette.requests import Request
from starlette.responses import Response

from src.settings import (
    AUTH_COOKIE_NAME,
    AUTH_COOKIE_SECURE,
    AUTH_SESSION_SECRET,
    AUTH_SESSION_TTL,
)
from src.settings import ConfigError


# Domain-separation salt so the session secret isn't reused verbatim for other
# signing contexts if more itsdangerous-based signers are added later.
_SALT = "lawbench-session-v1"


class SessionError(Exception):
    """A session cookie was present but malformed / not a valid payload dict."""


def _serializer() -> URLSafeTimedSerializer:
    """Build the signer lazily so the module imports without a configured secret.

    Raises :class:`~src.settings.ConfigError` at first use (i.e. at request time
    via ``create_app``'s fail-fast, or when a route touches the session) if the
    deploy secret was never set — fail closed, never sign with an empty key.
    """
    if not AUTH_SESSION_SECRET:
        raise ConfigError(
            "AUTH_SESSION_SECRET is not set — refusing to sign sessions. "
            "It must be a stable deploy secret (never auto-generated per restart)."
        )
    return URLSafeTimedSerializer(AUTH_SESSION_SECRET, salt=_SALT)


def _normalize(payload: dict[str, Any]) -> dict[str, Any]:
    """Coerce a session payload to the canonical shape (all keys present).

    ``sub`` must be a non-empty string (the stable Logto user id); the rest
    default to empty values when the IdP didn't supply them. ``scopes`` is forced
    to a list of strings; the resolver checks it directly on every request (see
    :mod:`scopes`), so a stale or tampered cookie cannot widen access beyond the
    scopes it carries.
    """
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise SessionError("session payload missing a non-empty 'sub'")

    scopes = payload.get("scopes", [])
    if not isinstance(scopes, list):
        scopes = [scopes] if scopes else []
    scopes = [str(s) for s in scopes if s]

    return {
        "sub": sub,
        "name": str(payload.get("name", "") or ""),
        "email": str(payload.get("email", "") or ""),
        "scopes": scopes,
    }


def set_session(response: Response, payload: dict[str, Any]) -> None:
    """Sign ``payload`` and set the session cookie on ``response``.

    Called from the ``/auth/callback`` handler after the id token is validated.
    The payload is normalized first so a caller that omits optional fields
    still writes a well-formed cookie. ``max_age`` mirrors the serializer's
    cryptographic TTL so the browser discards the cookie when the signature
    would also reject it.
    """
    normalized = _normalize(payload)
    token = _serializer().dumps(normalized)
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        max_age=AUTH_SESSION_TTL,
        httponly=True,  # no JS access — fixed security attribute
        secure=AUTH_COOKIE_SECURE,
        samesite="lax",  # CSRF resistance for top-level navigations — fixed
        path="/",
    )


def get_session(request: Request) -> dict[str, Any] | None:
    """Read + verify the session cookie, returning the payload or ``None``.

    ``None`` means "no session" (no cookie, expired signature, or bad
    signature) — the caller treats that as "unauthenticated, try the next
    channel". A present-but-*malformed* payload (valid signature, wrong shape)
    raises :class:`SessionError` so :mod:`deps` can bind it to a 401 rather than
    silently fall through — present-but-invalid is binding, never weaker.
    """
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if not token:
        return None
    try:
        payload = _serializer().loads(token, max_age=AUTH_SESSION_TTL)
    except SignatureExpired:
        return None  # expired — treat as no session, let the caller re-auth
    except BadSignature:
        return None  # tampered / wrong key — treat as no session
    if not isinstance(payload, dict):
        raise SessionError("session payload is not a dict")
    return _normalize(payload)


def clear_session(response: Response) -> None:
    """Delete the session cookie (logout).

    ``max_age=0`` + overwriting the value expires it immediately; ``path="/"``
    must match the ``set_session`` path or the browser keeps the old cookie.
    """
    response.delete_cookie(AUTH_COOKIE_NAME, path="/")
