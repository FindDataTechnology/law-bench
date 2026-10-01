"""Search routes: ``/api/search`` (JSON) + ``/search`` (HTML page).

Both delegate to ``src.search.query.search``. A missing/empty query returns
``[]``; a backend failure returns 503 (API) or a flash (page) so the rest of the
app stays usable when Elasticsearch/OpenRouter are down.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..templating import templates as _templates

router = APIRouter(tags=["search"])


@router.get("/api/search")
def search_api(q: str, top_k: int = 5):
    """Ranked chunks for a natural-language query; ``[]`` when nothing matches."""
    if not q:
        return []
    from src.search.query import search as do_search

    try:
        return do_search(q, top_k=top_k)
    except Exception as e:
        return JSONResponse(status_code=503, content={"error": str(e)})


@router.get("/search", include_in_schema=False, name="page_search")
def search_page(request: Request, q: str = ""):
    from src.search.query import search as do_search

    results: list[dict] = []
    error: str | None = None
    if q:
        try:
            results = do_search(q, top_k=10)
        except Exception as e:
            error = str(e)
    return _templates.TemplateResponse(
        request,
        "search.html",
        {"q": q, "results": results, "error": error},
    )
