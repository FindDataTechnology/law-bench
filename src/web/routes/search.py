"""Search routes: ``/api/search`` (JSON) + ``/search`` (HTML page).

Both delegate to ``src.search.query.search``. A missing/empty query returns
``[]``; a backend failure returns 503 (API) or a flash (page) so the rest of the
app stays usable when Elasticsearch/OpenRouter are down.

Domain parameter (change ``add-domain-rag-corpus-service``, design D4):

- **absent / empty / ``legal``** -> the exact legacy path: no extra checks, no
  DB touch, the legacy ``do_search`` call shape (the resolver's default index,
  ``settings.SEARCH_INDEX_NAME``). Byte-compat red line: existing callers,
  tests that fake ``src.search.query.search`` with the old signature, and the
  app-level auth semantics are all unchanged.
- **any other value** -> two sequential gates, then the query runs on the
  domain's registered index via ``src.search.resolver.resolve_index``. An
  unregistered domain is an honest 400 (``CorpusNotRegistered`` message names
  the domain), never a 404 and never an auto-created index.
- the gates run IN-HANDLER (not as route dependencies) because the domain rides
  a QUERY param while ``require_domain_role`` reads the ``domain_key`` PATH
  param — the check re-issues a Request whose ``path_params`` carry the domain.
  The constructor-resolved user is shared via ``request.state`` (FastAPI's
  per-request dependency cache guarantees the app-level ``get_current_user``
  has already run).
- **no authenticated identity** -> 401 unless the domain is the default.
- **API-key identities** (the ONLY live credential channel on the public
  read-only pod, ``src/web/public_app.py``) are pinned to the default legal
  path REGARDLESS of the ``domain`` param: the replica serves the default
  corpus only and never performs workspace-membership enforcement, so a
  non-legal domain is ignored there. Fail-safe by construction — the decision
  is documented here because the route module is shared by both apps.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from ..auth.deps import require_scope
from ..auth.domain_rbac import require_domain_role
from ..deps import DbConn, get_db
from ..templating import templates as _templates

router = APIRouter(tags=["search"])

DEFAULT_DOMAIN = "legal"


def _effective_domain(request: Request, domain: str | None, conn: Any) -> str | None:
    """Gate a non-default domain search; return the domain to search.

    Returns ``None`` when the request must fall back to the default (legal)
    path; returns the domain unchanged once both gates pass. Raises
    ``HTTPException`` (401/403) on denial — fail closed. See the module
    docstring for the full contract, including the public-pod API-key rule.
    """
    if not domain or domain == DEFAULT_DOMAIN:
        return None
    user = getattr(request.state, "user", None)
    channel = getattr(user, "channel", "")
    if user is None or channel == "anonymous" or not getattr(user, "sub", ""):
        raise HTTPException(status_code=401, detail="not authenticated")
    if channel == "apikey":
        # Public read-only replica: serves the default (legal) path only; the
        # domain param is ignored (decision recorded in the module docstring).
        return None
    # Gate 1 — platform scope (Logto vocabulary; ``*`` is a wildcard).
    require_scope("content:read")(user=user)
    # Gate 2 — domain membership (workspace record is the only source of
    # domain roles). The RBAC factory reads ``domain_key`` from PATH params;
    # re-issue the request with the QUERY domain injected as the path param.
    gated_request = Request(
        {**request.scope, "path_params": {**request.path_params, "domain_key": domain}}
    )
    require_domain_role("annotator")(gated_request, user=user, conn=conn)
    return domain


@router.get("/api/search")
def search_api(request: Request, q: str, top_k: int = 5, domain: str | None = None):
    """Ranked chunks for a natural-language query; ``[]`` when nothing matches.

    ``domain`` is optional: absent/``legal`` keeps the legacy behavior
    verbatim; any other value is domain-gated (see module docstring) and hits
    the domain's registered index. Unregistered domain -> 400 with the
    resolver's honest message.
    """
    if not q:
        return []
    from src.search.query import search as do_search

    index_name = None
    if domain and domain != DEFAULT_DOMAIN:
        conn = get_db()  # lazy: the default path never touches the DB
        gated = _effective_domain(request, domain, conn)
        if gated is not None:
            from src.search.resolver import CorpusNotRegistered, resolve_index

            try:
                index_name = resolve_index(conn, gated)
            except CorpusNotRegistered as exc:
                # 未登记域如实 (spec 域化检索与授权): honest 400 naming the
                # domain — not a 404, and no index is created as a side effect.
                return JSONResponse(status_code=400, content={"error": str(exc)})
    try:
        if index_name is not None:
            return do_search(q, top_k=top_k, index_name=index_name)
        return do_search(q, top_k=top_k)  # legacy call shape — byte-compat
    except Exception as e:
        return JSONResponse(status_code=503, content={"error": str(e)})


@router.get("/api/library/search")
def library_search_api(
    request: Request,
    q: str,
    top_k: int = 5,
    domain: str = DEFAULT_DOMAIN,
    db: DbConn = Depends(get_db),
):
    """Domain-scoped retrieval over the shared libraries (JSON).

    This is the machine-facing counterpart of the knowledge area's search box:
    it resolves the caller's **effective** subscription (inheritance, narrowing)
    and queries each library with the model that built it. Nothing is copied —
    an external library is read where it lives.

    Status code contract, so a caller can tell the three outcomes apart:

    - ``200`` + hits (possibly ``[]``: a miss inside a real corpus);
    - ``400`` + ``{"error": ...}`` when the domain subscribes to no corpus at
      all — "nothing to search" is not "no match";
    - ``502`` + ``{"error": ...}`` when an upstream store or embedder fails,
      because that is not the caller's mistake and not an empty result.
    """
    from src.search import library_index

    if not q:
        return []
    # Injected, never fetched directly: `get_db()` called inside a handler
    # bypasses dependency overrides, so a test would silently hit the real
    # database while the rest of the request used the overridden one.
    conn = db
    gated = _effective_domain(request, domain, conn)
    target = gated or domain or DEFAULT_DOMAIN
    row = conn.execute(
        "SELECT path FROM domains WHERE key = %s", (target,)
    ).fetchone()
    if row is None:
        return JSONResponse(status_code=404, content={"error": f"unknown domain {target!r}"})
    try:
        hits = library_index.search(
            conn, domain_path=row["path"], query=q, top_k=max(1, min(top_k, 50))
        )
    except library_index.NotSubscribed as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except Exception as exc:
        return JSONResponse(
            status_code=502, content={"error": f"{type(exc).__name__}: {exc}"}
        )
    return {"domain": target, "q": q, "hits": hits}


@router.get("/search", include_in_schema=False, name="page_search")
def search_page(request: Request, q: str = "", domain: str | None = None):
    """HTML search page; same ``domain`` semantics as :func:`search_api`.

    An unregistered domain renders the honest 「该域未登记 RAG 语料」 error
    (not the generic backend-down flash); a registered one is surfaced in the
    page title and the results header.
    """
    from src.search.query import search as do_search

    results: list[dict] = []
    error: str | None = None
    unregistered = False
    index_name = None
    if q and domain and domain != DEFAULT_DOMAIN:
        conn = get_db()
        gated = _effective_domain(request, domain, conn)
        if gated is not None:
            from src.search.resolver import CorpusNotRegistered, resolve_index

            try:
                index_name = resolve_index(conn, gated)
            except CorpusNotRegistered as exc:
                error = str(exc)
                unregistered = True
    if q and not unregistered:
        try:
            if index_name is not None:
                results = do_search(q, top_k=10, index_name=index_name)
            else:
                results = do_search(q, top_k=10)
        except Exception as e:
            error = str(e)
    return _templates.TemplateResponse(
        request,
        "search.html",
        {
            "q": q,
            "results": results,
            "error": error,
            "unregistered": unregistered,
            "domain": domain or "",
        },
    )
