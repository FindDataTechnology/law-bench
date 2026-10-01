"""Logto OIDC client: discovery, JWKS, JWT validation, PKCE token exchange.

The ONLY module that talks to the Logto IdP. It owns:

- the OIDC discovery-document fetch + cache,
- the JWKS fetch + cache with refetch-on-unknown-``kid`` (Logto rotates signing
  keys; a stale cache misses the new ``kid`` -> one refetch resolves it),
- access-token JWT validation — signature (ES384 via JWKS), ``iss`` (the
  discovery issuer), ``exp``, and ``aud`` (the ``LOGTO_API_RESOURCE`` audience
  when configured),
- the authorization-code token exchange (PKCE S256),
- the authorize / end-session URL builders.

Fail-closed posture: :func:`verify_reachable` eagerly fetches discovery + JWKS
at startup so an unreachable IdP / JWKS prevents the process from serving
traffic (no open server). At request time, a JWKS network failure during
:func:`validate_jwt` surfaces as :class:`LogtoUnreachable` (-> 503) — it is NOT
swallowed into a 401, because 401 implies the token was *rejected* rather than
*unchecked*; accepting would be open, 401 would lie about the cause.

Uses ``httpx`` for HTTP (honors ``HTTP_PROXY``/``HTTPS_PROXY``/``NO_PROXY`` via
``trust_env``) and ``pyjwt`` + ``cryptography`` (already available transitively)
for ES384 JWKS validation.
"""

from __future__ import annotations

import threading
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from jwt import InvalidTokenError as _PyJwtError

from src.settings import (
    LOGTO_API_RESOURCE,
    LOGTO_CLIENT_ID,
    LOGTO_CLIENT_SECRET,
    LOGTO_ENDPOINT,
    LOGTO_SCOPES,
)


class LogtoError(Exception):
    """Base for Logto OIDC client failures (token exchange, userinfo, ...)."""


class LogtoUnreachable(LogtoError):
    """The IdP / JWKS could not be reached or returned a malformed doc.

    Fail-closed signal: callers must NOT treat this as "token invalid"; the
    token was *unverifiable*, not *rejected*. Startup raises this to prevent an
    open server; request-time raises surface as 503.
    """


class InvalidToken(LogtoError):
    """A Bearer JWT failed structural or cryptographic validation (-> 401)."""


# --- module-level caches + HTTP client ------------------------------------- #
#
# Discovery + JWKS are process-wide cached and refreshed only on demand (force
# or unknown-kid). A long-lived shared httpx.Client reuses the connection pool
# across threads; httpx clients are thread-safe for issuing requests.
_discovery: dict[str, Any] | None = None
_jwks: dict[str, Any] | None = None
# RLock (reentrant): ``_fetch_jwks`` calls ``fetch_discovery`` while still
# holding the cache lock to resolve ``jwks_uri``, and ``get_signing_key``'s
# refetch-on-unknown-kid path re-enters ``_fetch_jwks``. A plain Lock would
# deadlock the same thread on both paths; RLock permits the nested acquisition.
_cache_lock = threading.RLock()

_client: httpx.Client | None = None
_client_lock = threading.Lock()
_HTTP_TIMEOUT = httpx.Timeout(10.0)


def _get_client() -> httpx.Client:
    """Lazily build a shared httpx client (trust_env -> dev/proxy env honored)."""
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is None:
            _client = httpx.Client(
                timeout=_HTTP_TIMEOUT, follow_redirects=True, trust_env=True
            )
    return _client


def _discovery_url() -> str:
    if not LOGTO_ENDPOINT:
        raise LogtoError("LOGTO_ENDPOINT is not configured")
    return f"{LOGTO_ENDPOINT}/oidc/.well-known/openid-configuration"


# --- discovery + JWKS ------------------------------------------------------ #


def fetch_discovery(force: bool = False) -> dict[str, Any]:
    """Fetch and cache the OIDC discovery document.

    The doc rarely changes (it carries the issuer + endpoint URLs), so it is
    cached for process lifetime unless ``force`` refreshes it (used after an
    unreachable event or for tests). Raises :class:`LogtoUnreachable` on network
    failure or a doc missing required fields — fail-closed.
    """
    global _discovery
    with _cache_lock:
        if _discovery is not None and not force:
            return _discovery
        try:
            resp = _get_client().get(_discovery_url())
            resp.raise_for_status()
            doc = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LogtoUnreachable(f"discovery fetch failed: {exc}") from exc
        for field in ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri"):
            if not doc.get(field):
                raise LogtoUnreachable(f"discovery doc missing '{field}'")
        _discovery = doc
        return _discovery


def _fetch_jwks(force: bool = False) -> dict[str, Any]:
    """Fetch and cache the IdP JWKS (fail-closed on network/malformed errors)."""
    global _jwks
    with _cache_lock:
        if _jwks is not None and not force:
            return _jwks
        uri = fetch_discovery()["jwks_uri"]
        try:
            resp = _get_client().get(uri)
            resp.raise_for_status()
            jwks = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LogtoUnreachable(f"JWKS fetch failed: {exc}") from exc
        if "keys" not in jwks or not isinstance(jwks["keys"], list):
            raise LogtoUnreachable("JWKS missing a 'keys' list")
        _jwks = jwks
        return _jwks


def _find_key(jwks: dict[str, Any], kid: str | None) -> dict[str, Any] | None:
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key
    return None


def get_signing_key(kid: str | None) -> Any:
    """Return a cryptography key for ``kid`` (refetch JWKS once on a miss).

    A ``kid`` absent from the cache usually means Logto rotated a key and the
    cache is stale; one forced refetch resolves it. A second miss means the
    token was minted by a different IdP (or post-dates a key we cannot see) ->
    reject (:class:`InvalidToken`), fail-closed.
    """
    key = _find_key(_fetch_jwks(), kid)
    if key is None:  # refetch-on-unknown-kid
        key = _find_key(_fetch_jwks(force=True), kid)
    if key is None:
        raise InvalidToken(f"no signing key for kid={kid!r}")
    # PyJWK wraps a JWK dict -> .key is the ES384 public key jwt.decode accepts.
    return jwt.PyJWK(key).key


# --- JWT validation -------------------------------------------------------- #


def validate_jwt(token: str) -> dict[str, Any]:
    """Validate a Logto-issued Bearer JWT and return its claims.

    Verifies the ES384 signature via the IdP JWKS, the ``iss`` (the discovery
    issuer), ``exp``, and ``aud`` (the ``LOGTO_API_RESOURCE`` identifier, falling
    back to the client id when no API Resource is configured). Raises
    :class:`InvalidToken` (-> 401) on any structural/crypto failure; lets
    :class:`LogtoUnreachable` (-> 503) propagate from a JWKS network failure so
    the cause is reported honestly rather than masked as a bad token.
    """
    try:
        header = jwt.get_unverified_header(token)
    except _PyJwtError as exc:
        raise InvalidToken(f"malformed token header: {exc}") from exc

    signing_key = get_signing_key(header.get("kid"))
    issuer = fetch_discovery()["issuer"]

    options: dict[str, Any] = {
        "verify_signature": True,
        "require": ["exp", "iss", "sub"],
    }
    decode_kwargs: dict[str, Any] = {
        "algorithms": ["ES384"],
        "issuer": issuer,
        "audience": LOGTO_API_RESOURCE or LOGTO_CLIENT_ID,
        "options": options,
    }

    try:
        return jwt.decode(token, signing_key, **decode_kwargs)
    except _PyJwtError as exc:
        raise InvalidToken(str(exc)) from exc


def validate_id_token(token: str) -> dict[str, Any]:
    """Validate a Logto-issued ``id_token`` and return its claims.

    The id_token's audience is always the client (per OIDC core), so this
    checks ``aud == LOGTO_CLIENT_ID`` *regardless* of ``LOGTO_API_RESOURCE``
    (which governs Bearer access-token validation in :func:`validate_jwt`).
    The ``/auth/callback`` uses this to securely extract the user's identity
    rather than trusting the token-response JSON, which is unverified payload.
    """
    try:
        header = jwt.get_unverified_header(token)
    except _PyJwtError as exc:
        raise InvalidToken(f"malformed id_token header: {exc}") from exc

    signing_key = get_signing_key(header.get("kid"))
    issuer = fetch_discovery()["issuer"]
    try:
        return jwt.decode(
            token,
            signing_key,
            algorithms=["ES384"],
            issuer=issuer,
            audience=LOGTO_CLIENT_ID,
            options={
                "verify_signature": True,
                "require": ["exp", "iss", "sub", "aud"],
            },
        )
    except _PyJwtError as exc:
        raise InvalidToken(str(exc)) from exc


def fetch_userinfo(access_token: str) -> dict[str, Any]:
    """GET the OIDC userinfo endpoint with the Bearer access token.

    Access tokens carry ``sub`` + scopes but not always the profile claims
    (``name``/``email``); userinfo fills those. Returns ``{}`` when the IdP
    advertises no userinfo endpoint (still valid — deps falls back to ``sub``).
    """
    disc = fetch_discovery()
    endpoint = disc.get("userinfo_endpoint")
    if not endpoint:
        return {}
    try:
        resp = _get_client().get(
            endpoint, headers={"Authorization": f"Bearer {access_token}"}
        )
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise LogtoError(f"userinfo fetch failed: {exc}") from exc


# --- authorization-code flow (PKCE) --------------------------------------- #


def build_authorize_url(state: str, code_challenge: str, redirect_uri: str) -> str:
    """Construct the Logto ``/authorize`` URL (response_type=code, PKCE S256).

    When an API Resource is configured, ``resource=<LOGTO_API_RESOURCE>`` is
    included so Logto mints an access token for that resource; its ``scope``
    claim is then the user's granted permission subset (the app's authorization
    truth). Without it, only identity scopes are returned.
    """
    disc = fetch_discovery()
    params = {
        "client_id": LOGTO_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(LOGTO_SCOPES),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if LOGTO_API_RESOURCE:
        params["resource"] = LOGTO_API_RESOURCE
    return f"{disc['authorization_endpoint']}?{urlencode(params)}"


def exchange_code(code: str, code_verifier: str, redirect_uri: str) -> dict[str, Any]:
    """Exchange an authorization code + PKCE verifier for a token response.

    Sends ``client_secret`` when configured (confidential client) and repeats the
    ``resource`` indicator when an API Resource is configured, so the returned
    access token is minted for that audience. Raises :class:`LogtoUnreachable` on
    a transport failure, :class:`LogtoError` on a non-200 token endpoint (bad
    code/verifier/state -> route maps to 400).
    """
    disc = fetch_discovery()
    data: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": LOGTO_CLIENT_ID,
        "code_verifier": code_verifier,
    }
    if LOGTO_API_RESOURCE:
        data["resource"] = LOGTO_API_RESOURCE
    if LOGTO_CLIENT_SECRET:
        data["client_secret"] = LOGTO_CLIENT_SECRET
    try:
        resp = _get_client().post(disc["token_endpoint"], data=data)
    except httpx.HTTPError as exc:
        raise LogtoUnreachable(f"token exchange transport error: {exc}") from exc
    if resp.status_code != 200:
        raise LogtoError(
            f"token endpoint returned {resp.status_code}: {resp.text}"
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise LogtoError(f"token endpoint returned non-JSON: {exc}") from exc


def end_session_url(
    id_token_hint: str | None, post_logout_redirect_uri: str | None
) -> str | None:
    """Build the Logto end-session URL, or ``None`` if discovery has none.

    ``client_id`` is always sent: Logto's upstream (node-oidc-provider) resolves
    the client from ``id_token_hint`` or ``client_id``, and if neither is present
    it **silently drops** ``post_logout_redirect_uri`` — sending the user to the
    generic end-session success page instead of back to the app.
    """
    endpoint = fetch_discovery().get("end_session_endpoint")
    if not endpoint:
        return None
    params: dict[str, str] = {}
    if LOGTO_CLIENT_ID:
        params["client_id"] = LOGTO_CLIENT_ID
    if id_token_hint:
        params["id_token_hint"] = id_token_hint
    if post_logout_redirect_uri:
        params["post_logout_redirect_uri"] = post_logout_redirect_uri
    qs = urlencode(params)
    return f"{endpoint}?{qs}" if qs else endpoint


# --- startup reachability check ------------------------------------------- #


def verify_reachable() -> None:
    """Eagerly fetch discovery + JWKS so startup fails-closed on an unreachable IdP.

    Called from ``create_app()`` (Phase 2 wiring); a failure raises
    :class:`LogtoUnreachable`, which the caller surfaces as
    :class:`~src.settings.ConfigError` so the process refuses to boot rather than
    run an open server. Also warms both caches so the first request isn't
    penalized with the IdP round-trip.
    """
    fetch_discovery()
    _fetch_jwks()
