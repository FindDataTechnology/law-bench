"""Public app factory for China-facing read-only API pod.

This module provides `create_public_app()` — a standalone FastAPI instance that
mounts only the read-heavy router subset for the public API service deployed in
China. It is intentionally structurally separate from `create_app()` (app.py) to
keep the origin app untouched and avoid coupling concerns through boolean flags.

## Public router subset (read-only)

Mounted routes:
- `contract_context`: READ paths only (`GET /api/contracts`, `/{type}`, `/slots`,
  `/laws`, `/tags`, `/clauses`, `/artifacts*`; **EXCLUDES** `POST /generate` and
  `POST /generate-stored` which are moved elsewhere).
- `contracts`: Browse + download (`GET /contracts`, `/{type}`, `/download/*`).
- `samples`: Artifact browse API (JSON listing, no HTML page chrome).
- `search`: Query API (`GET /api/search`, `GET /search`).
- `law_info`: Law references (`GET /law-info`, `/{type}`, `/law-references`).
- `clauses`: READ paths only (`GET /clauses`, `/{type}`, `/generate`, `/new`,
  `/clauses/{id}`, `/review`; **EXCLUDES** POST routes for CRUD).

Deliberately excluded (not mounted):
- `api`: CRUD for rubrics/prompts/compare/evaluate/harbor.
- `generation`: Modes D/E/F/G (`generate-batch`, `pipeline`, `auto-reject`,
  `regenerate-template`, `generation-jobs`).
- `dashboard`: Admin interface.
- `pages`: HTML chrome (rubrics/prompts/compare pages).
- `auth`: OIDC login + key issuance (`/auth/*`, `/api/keys`).

## Auth posture

Constructor-level dependency `dependencies=[Depends(get_current_user)]` is reused
unchanged so every mounted route inherits authentication. The `get_current_user`
dependency resolves identity via cookie → Bearer JWT → X-API-Key (first success;
present-but-invalid is binding). On the public pod:
- Session cookies and Logto-JWKS Bearer tokens are effectively dormant (no
  browser login mounted, Logto unreachable across GFW).
- X-API-Key is the live channel; keys are issued on origin and handed to callers
  out-of-band. Key *verification* happens on the public pod via local lookup in
  the replicated `api_keys` table.

## Startup behavior

Unlike `create_app()`, this factory does NOT call `logto.verify_reachable()` or
fail if Logto env vars are absent. It substitutes `check_public_auth_config()`
which verifies: DATABASE_URL reachable, api_keys table present, AUTH_SESSION_SECRET
set (so the dormant cookie path does not crash). The pod fails-closed on missing
AUTH_SESSION_SECRET but never depends on cross-border JWKS fetches at boot.

## Docs surface

Docs are locked down: `docs_url=None`, `redoc_url=None`, `openapi_url=None`. The
public endpoint shape does not leak from China; `/openapi.json`, `/api/docs`,
`/redoc` all return 404. `/healthz` remains 200 unauthenticated (liveness/readiness
probe target).

## Read-replica considerations

The public pod reads from a local Postgres read-replica fed by logical replication.
When `X-API-Key` verify touches `last_used_at`, the write is best-effort (wrapped
in try/except OperationalError); a failed touch MUST NOT cause 401/500. This is
scoped to the public pod only — origin keeps real touches. A `READONLY_REPLICA`
env flag (default 0) can skip the write entirely on replicas to avoid per-request
error noise.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .auth.deps import get_current_user
from .deps import DbConn, get_db
from .paths import STATIC_DIR
from .routes import (
    clauses,
    contract_context,
    contracts,
    law_info,
    samples,
    search,
)
from src.settings import check_public_auth_config


def _make_handler(status: int):
    """Map ManageError subclasses to HTTP status codes."""

    async def handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status, content={"error": str(exc)})

    return handler


def create_public_app() -> FastAPI:
    """Construct the public-facing read-only FastAPI application.

    Returns:
        FastAPI instance with constructor-level auth, docs disabled, read-only
        router subset mounted, and fail-closed startup config.
    """
    app = FastAPI(
        title="Public Law Bench API",
        # Lock down docs surface: /openapi.json, /api/docs, /redoc all 404.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        # Constructor-level auth: every route inherits get_current_user. The shared
        # dependency resolves cookie → Bearer → X-API-Key in order; present-but-
        # invalid is binding (401). On the public pod, X-API-Key is the live channel;
        # session/JWKS paths are dormant but still registered (cookie signing needs
        # AUTH_SESSION_SECRET, so we check it at startup).
        dependencies=[Depends(get_current_user)],
    )

    @app.middleware("http")
    async def _locale_middleware(request: Request, call_next):
        """Resolve locale once per request and persist as a cookie."""
        from .i18n import resolve_locale

        lang, t = resolve_locale(request)
        request.state.lang = lang
        request.state.t = t
        response = await call_next(request)
        response.set_cookie("lang", lang, samesite="lax", max_age=60 * 60 * 24 * 365)
        return response

    # Map manage-layer errors to HTTP statuses.
    from src.eval.manage import (
        ConflictError,
        HarborReadOnlyError,
        ManageError,
        NotFoundError,
        ValidationError,
    )

    _ERR_STATUS = [
        (NotFoundError, 404),
        (HarborReadOnlyError, 403),
        (ConflictError, 409),
        (ValidationError, 400),
    ]

    for exc_cls, status in _ERR_STATUS:
        app.add_exception_handler(exc_cls, _make_handler(status))

    @app.exception_handler(ManageError)
    async def _fallback(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> JSONResponse:
        """Liveness/readiness probe target: always 200 when the process is up.

        Exempt from auth checks — the dependency logic short-circuits exempt paths.
        """
        return JSONResponse({"status": "ok"})

    @app.on_event("startup")
    def _check_public_auth_config_startup() -> None:
        """Fail-closed auth readiness: verify minimal config without Logto.

        Unlike `create_app()`, this factory MUST NOT call `logto.verify_reachable()`
        because the China box has no `LOGTO_*` env and cannot reliably reach
        `auth.finddatatech.cloud` across the border. Instead, we verify:
        - DATABASE_URL reachable (replica connection works)
        - api_keys table present (can verify keys locally)
        - AUTH_SESSION_SECRET set (so the dormant cookie path does not crash on import)

        If any check fails, raise ConfigError and refuse to bind. Preserves the
        origin's fail-closed posture: the public pod never runs as an open server
        even if its env is misconfigured.
        """
        check_public_auth_config()

    # Mount the public router subset (read-only). Note: contract_context and clauses
    # are mixed routers that have POST write routes; those must be split out beforehand
    # so they're not mounted here. Design decision D2 mandates behavior-preserving
    # router separation: origin includes both read+write routers; public includes
    # only the read router.

    # contract_context: read paths only (POST /generate and POST /generate-stored
    # should be moved to generation.py or a separate write router before mounting).
    # See design.md D2 for the split pattern.
    app.include_router(contract_context.read_only_router)

    # contracts: browse + download (already read-only in source).
    app.include_router(contracts.router)

    # samples: JSON artifact listing (read-only; HTML page not mounted).
    app.include_router(samples.router)

    # search: query API (read-only).
    app.include_router(search.router)

    # law_info: law references (read-only).
    app.include_router(law_info.router)

    # clauses: read paths only (POST routes for CRUD must be split out first).
    app.include_router(clauses.read_only_router)

    # In-process rate-limit middleware (the abuse half of "防止恶意调用").
    # Env-gated inside add_rate_limit_middleware: when RATE_LIMIT_ENABLED=1 (the
    # public pod), a token-bucket limiter is installed as the outermost HTTP
    # middleware so over-limit callers get 429 + Retry-After; when unset/"0" the
    # function is a no-op and the request path is unchanged. A gateway-level
    # limiter (Caddy rate_limit) is the preferred production posture; this is the
    # no-gateway fallback. See docs/public-api-deploy.md.
    from .rate_limit import add_rate_limit_middleware

    add_rate_limit_middleware(app)

    return app


# Module-level ASGI instance for ``uvicorn src.web.public_app:app`` (public pod).
# Constructed at import time; the fail-closed ``check_public_auth_config()`` runs
# only on the startup event (not at import), so importing this module is safe in
# tests and never blocks on missing env. The origin image serves
# ``src.web.app:app``; ``scripts/docker-entrypoint.sh`` selects this object when
# ``PUBLIC_API=1`` so the same image runs either factory based on env alone.
app = create_public_app()
