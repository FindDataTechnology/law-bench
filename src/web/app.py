"""FastAPI application for browsing and managing evaluation rules.

Run locally with::

    uv run uvicorn src.web.app:app --reload --host 127.0.0.1 --port 8010

All routers — the HTML pages (``src/web/routes/pages.py`` and siblings) and
the JSON API (``src/web/routes/api.py``) — are included unconditionally at
module load, so a missing or broken router surfaces at startup instead of
404-ing silently at request time. Manage-layer errors (``src/eval/manage.py``)
are mapped to HTTP statuses here so routes stay thin. The Jinja2 ``templates``
renderer lives in ``src/web/templating.py`` (not here) so the HTML route
modules can import it without a circular import through this module.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.eval.manage import (
    ConflictError,
    HarborReadOnlyError,
    ManageError,
    NotFoundError,
    ValidationError,
)

from .i18n import resolve_locale
from .paths import STATIC_DIR, TEMPLATES_DIR
from .routes import (
    admin,
    api,
    console,
    auth,
    authoring,
    clauses,
    contract_context,
    contracts,
    copilot,
    dashboard,
    distribution,
    generation,
    law_catalog,
    law_info,
    pages,
    promotion,
    review,
    samples,
    search,
)

from src.settings import check_auth_config
from .auth import logto
from .auth.deps import get_current_user


# ManageError subclass -> HTTP status.
_ERR_STATUS = [
    (NotFoundError, 404),
    (HarborReadOnlyError, 403),
    (ConflictError, 409),
    (ValidationError, 400),
]


def _make_handler(status: int):
    async def handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status, content={"error": str(exc)})

    return handler


def _wants_html(request: Request) -> bool:
    """Is this a browser navigation (vs an API/script call)?

    A top-level browser navigation sends ``Sec-Fetch-Mode: navigate`` and an
    Accept of ``text/html``; a fetch()/curl call sends ``Sec-Fetch-Mode: cors``
    (or no Sec-Fetch-Mode) and ``*/*`` or ``application/json``. We redirect only
    navigations so the documented 401 JSON behavior for API callers is unchanged.
    """
    if request.headers.get("sec-fetch-mode", "") == "navigate":
        return True
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "application/json" not in accept


def create_app() -> FastAPI:
    app = FastAPI(
        title="Evaluation Rules Manager",
        docs_url="/api/docs",
        # App-level auth: every route inherits get_current_user. Exempt paths
        # (/healthz, /auth/*) short-circuit inside the dep to an anonymous
        # sentinel, so the login flow and liveness probe stay reachable.
        dependencies=[Depends(get_current_user)],
    )

    # Ensure the asset dirs exist so the mounts/templating work on first run.
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(api.router)
    app.include_router(admin.router)
    app.include_router(authoring.router)
    app.include_router(auth.router)
    app.include_router(copilot.router)
    app.include_router(contract_context.router)
    app.include_router(generation.router)
    app.include_router(pages.router)
    app.include_router(samples.router)
    app.include_router(law_info.router)
    app.include_router(law_catalog.router)
    app.include_router(search.router)
    app.include_router(contracts.router)
    app.include_router(clauses.router)
    app.include_router(review.router)
    app.include_router(promotion.router)
    app.include_router(dashboard.router)
    # Logto-free machine surface: /api/v1/distribution/* is exempted from the
    # app-level get_current_user (see auth.deps._EXEMPT_PREFIXES) and does its
    # own X-Consumer-Token auth; not mounted on public_app.
    app.include_router(distribution.router)
    app.include_router(console.read_only_router)
    app.include_router(console.write_router)

    # Resolve the active locale once per request, stash it for the template
    # context processor, and persist the choice as a cookie so it sticks.
    @app.middleware("http")
    async def _locale_middleware(request: Request, call_next):
        lang, t = resolve_locale(request)
        request.state.lang = lang
        request.state.t = t
        response = await call_next(request)
        # Refresh the cookie on every response so the resolved locale persists
        # (covers both explicit switches and first-visit defaulting to zh).
        response.set_cookie("lang", lang, samesite="lax", max_age=60 * 60 * 24 * 365)
        return response

    # Map manage-layer errors to HTTP statuses.
    for exc_cls, status in _ERR_STATUS:
        app.add_exception_handler(exc_cls, _make_handler(status))

    @app.exception_handler(ManageError)
    async def _fallback(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.exception_handler(StarletteHTTPException)
    async def _auth_redirect(request: Request, exc: StarletteHTTPException):
        """Make the login flow discoverable: a 401 on a *browser* navigation
        (Accept: text/html, or Sec-Fetch-Mode: navigate) 302s to /auth/login so a
        human can sign in; API calls (curl, XHR, fetch — Accept is ``*/*`` or
        ``application/json``) keep the default JSON ``{"detail": ...}``. Without
        this, visiting any page unauthenticated returns bare
        ``{"detail":"not authenticated"}`` and a human has no way to reach the
        sign-in page. The redirect only starts the flow — /auth/callback sets the
        session cookie, and every authenticated request still goes through
        get_current_user. ``next`` is validated same-origin in the callback, so
        this is not an open-redirect sink.
        """
        if exc.status_code == 401 and _wants_html(request):
            return RedirectResponse(
                url=f"/auth/login?next={quote(request.url.path)}",
                status_code=302,
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=getattr(exc, "headers", None),
        )

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> JSONResponse:
        """Liveness/readiness probe target: always 200 when the process is up.

        附带检索计数（审计 03 §11）。**刻意不改状态码**：探针非 200 会让 k8s
        重启本来健康的 pod——一次 ES 抖动不该把「降级」放大成「停机」。
        计数只是信息，让人能从 `kubectl exec ... /healthz` 看出「这个进程
        一直在裸起草」，而不是去翻日志。
        """
        payload: dict = {"status": "ok"}
        try:
            from ..search.rag_tool import retrieval_stats

            payload["retrieval"] = retrieval_stats()
        except Exception:  # noqa: BLE001 - 探针不许因附加信息失败
            pass
        return JSONResponse(payload)

    @app.on_event("startup")
    def _verify_auth_startup() -> None:
        """Fail-closed auth readiness: refuse to serve if auth env is unset or
        the Logto IdP / JWKS is unreachable — never run an open server. Also
        warms the discovery + JWKS caches so the first request isn't penalized.
        """
        check_auth_config()
        logto.verify_reachable()

    @app.on_event("startup")
    def _load_tag_vocab() -> None:
        """Populate the in-memory tag vocabulary from the ``tag_dims`` table so
        the dashboard facets / ``validate_tags`` see the full controlled
        vocabulary without reading seed files from the image. Best-effort: a DB
        hiccup must not block startup (the starter set still works)."""
        try:
            from ..clauses.tags import load_vocab_from_db
            load_vocab_from_db()
        except Exception:  # noqa: BLE001
            pass

    @app.on_event("startup")
    def _reap_stale_generation_jobs() -> None:
        """把上个进程遗留的 pending/running 生成任务收成 failed（审计 03 §10）。

        `generation_jobs` 的终态只有后台任务自己在同一进程里写；滚动部署 / OOM /
        驱逐 / SIGTERM 落在 202 与收尾之间，就会留下永远「还在跑」的行。启动时本
        进程还没有任何任务，所以凡是非终态行必是上一进程遗留，可无条件收掉。
        Best-effort：数据库打嗝不该拦住启动（下次重启还会再扫）。
        """
        try:
            from ..eval.store import reap_stale_generation_jobs

            n = reap_stale_generation_jobs()
            if n:
                logger.warning(
                    "reaped %s stale generation job(s) from a previous process", n
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("stale generation-job sweep skipped: %s", exc)

    return app


app = create_app()
