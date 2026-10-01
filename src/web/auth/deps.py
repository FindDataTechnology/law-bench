"""Unified auth dependency: resolve a request to a :class:`User`.

Three credential channels converge on one ``request.state.user``:

1. **Cookie** (strongest) — a signed httpOnly session cookie set at
   ``/auth/callback`` after the Logto id token was validated. The cookie's
   signature is the trust root; the IdP is not re-hit per request.
2. **Bearer** — a Logto-issued JWT (``Authorization: Bearer <jwt>``) validated
   against the IdP JWKS (:mod:`logto`).
3. **API key** — a self-managed ``X-API-Key`` (salted hash in the
   ``api_keys`` table, :mod:`apikey`).

Binding rule (security-required): a *present* credential that fails validation
is binding — it raises 401 and does NOT fall through to a weaker channel. So an
attacker who presents an invalid Bearer cannot be rescued by a valid API key
they also hold; an attacker with a tampered cookie cannot be rescued by a
Bearer. Only an *absent* credential falls through. This is why an expired
session cookie (present-but-invalid) yields 401, not a silent fall-through —
the user re-authenticates via ``/auth/login``.

Exempt paths (``/healthz``, ``/auth/*``) get an anonymous sentinel so the
constructor-level ``Depends(get_current_user)`` wired in Task 8.1 does not 401
the login flow or the liveness probe.

Authorization is scope-based: every channel carries the same Logto permission
vocabulary (``content:read`` / ``content:write`` / ``admin``). The cookie and
Bearer channels read it from the access token's ``scope`` claim (the cookie
persists the resolved scopes at ``/auth/callback``); the API-key channel carries
explicit scopes set at key creation. An identity with no recognized scope gets
no usable scope — fail closed. See :func:`require_scope`.

A JWKS network failure during Bearer validation is NOT swallowed into a 401:
``LogtoUnreachable`` propagates so the route layer maps it to 503 — 401 would
claim the token was *rejected* when it was merely *unverifiable*.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request

from src.settings import AUTH_COOKIE_NAME

from . import apikey, logto, session
from .scopes import scopes_from_claims


@dataclass
class User:
    """The resolved identity attached to ``request.state.user``.

    ``channel`` records which credential authenticated the request
    (``"cookie"`` | ``"bearer"`` | ``"apikey"`` | ``"anonymous"``) so logging
    and tests can tell them apart. ``anonymous`` marks an exempt path where auth
    was deliberately skipped; such routes must not consume the user.

    ``scopes`` is what authorization checks. For the cookie channel it is the
    scope set persisted at ``/auth/callback``; for the Bearer channel it is parsed
    directly from the access token's ``scope`` claim; for the API-key channel it is
    the key's stored scopes. All three are the same Logto permission vocabulary
    (``content:read`` / ``content:write`` / ``admin``), so the three channels
    enforce consistently. The app keeps no role table — roles are permission
    bundles that live in Logto.
    """

    sub: str
    name: str = ""
    email: str = ""
    scopes: list[str] = field(default_factory=list)
    channel: str = "anonymous"


# Paths exempt from auth. The constructor-level ``Depends(get_current_user)``
# wired in Task 8.1 applies to every route; these are the deliberate holes.
# ``/auth/*`` must be reachable pre-login (login starts the flow, callback
# completes it, logout clears the cookie); ``/healthz`` is the liveness probe.
# Exempt routes do not declare a ``user`` parameter, so the anonymous sentinel
# is never consumed.
_EXEMPT_PATHS: frozenset[str] = frozenset({"/healthz"})
_EXEMPT_PREFIXES: tuple[str, ...] = ("/auth/",)


def _is_exempt(path: str) -> bool:
    return path in _EXEMPT_PATHS or path.startswith(_EXEMPT_PREFIXES)


async def get_current_user(request: Request) -> User:
    """Resolve the request to a :class:`User`; raise 401 on no/invalid credential.

    See module docstring for the channel ordering and the present-but-invalid
    binding rule. Exempt paths get an anonymous sentinel (no 401).
    """
    path = request.url.path
    if _is_exempt(path):
        request.state.user = User(sub="", channel="anonymous")
        return request.state.user

    # 1. Cookie session (strongest — IdP-validated at callback, signed cookie).
    if request.cookies.get(AUTH_COOKIE_NAME):
        try:
            payload = session.get_session(request)
        except session.SessionError as exc:
            # Valid signature but malformed payload — present-but-invalid.
            raise HTTPException(status_code=401, detail="invalid session") from exc
        if payload is not None:
            user = User(
                sub=payload["sub"],
                name=payload.get("name", ""),
                email=payload.get("email", ""),
                scopes=[str(s) for s in payload.get("scopes", [])],
                channel="cookie",
            )
            request.state.user = user
            return user
        # Cookie was present but expired/tampered (get_session -> None).
        # Present-but-invalid is binding: 401, do NOT fall through to Bearer.
        raise HTTPException(status_code=401, detail="invalid or expired session")

    # 2. Bearer JWT (Logto-issued, JWKS-validated).
    authz = request.headers.get("authorization", "")
    if authz[:7].lower() == "bearer ":
        token = authz[7:].strip()
        if not token:
            raise HTTPException(status_code=401, detail="invalid bearer token")
        try:
            claims = logto.validate_jwt(token)
        except logto.InvalidToken as exc:
            # Present-but-invalid Bearer -> 401, do NOT fall through to API key.
            raise HTTPException(status_code=401, detail="invalid bearer token") from exc
        # logto.LogtoUnreachable propagates -> 503 (unverifiable, not rejected).
        # A Logto Bearer IS an access token, so its ``scope`` claim is the granted
        # permission set directly. A token with no admitted scope resolves to no
        # usable scopes (managed routes 403) — consistent with the cookie channel.
        user = User(
            sub=str(claims.get("sub", "")),
            name=str(claims.get("name", "") or ""),
            email=str(
                claims.get("email", "")
                or claims.get("preferred_username", "")
                or ""
            ),
            scopes=scopes_from_claims(claims),
            channel="bearer",
        )
        request.state.user = user
        return user

    # 3. X-API-Key (self-managed, salted hash — weakest channel, last resort).
    api_key_value = request.headers.get("x-api-key")
    if api_key_value:
        resolved = apikey.verify_key(api_key_value)
        if resolved is not None:
            user = User(
                sub=resolved["sub"],
                name=resolved.get("name", ""),
                email=resolved.get("email", ""),
                scopes=list(resolved.get("scopes", [])),
                channel="apikey",
            )
            request.state.user = user
            return user
        # Present-but-invalid/revoked/unknown -> 401 (no weaker channel left).
        raise HTTPException(status_code=401, detail="invalid api key")

    # No credential on a protected route.
    raise HTTPException(status_code=401, detail="not authenticated")


def require_scope(scope: str):
    """Dependency factory: require the current user to hold ``scope``.

    Usage::

        @router.post("/...", dependencies=[Depends(require_scope("write"))])

    A scope of ``"*"`` is a wildcard (grants all). An authenticated user
    without the scope gets 403 (authenticated but not permitted). Relies on
    :func:`get_current_user` having run first — FastAPI caches a dependency's
    result per request, so the constructor-level dep and this one share the
    same resolved :class:`User`.
    """

    def _checker(user: User = Depends(get_current_user)) -> User:
        if "*" in user.scopes or scope in user.scopes:
            return user
        raise HTTPException(status_code=403, detail=f"missing scope: {scope}")

    return _checker
