"""Law-info routes: ``/law-info`` (browse), ``/law-info/{type}`` (side-by-side
Doubao + DeepSeek survey), and ``/law-references`` (aggregated 法律法规 index).

Read-only HTML pages backed by the ``law_info`` table (seeded from the bundled
markdown by ``scripts/seed_law_info.py``). Markdown content is rendered to HTML
server-side (``src/web/markdown_render.py``). The aggregated index is computed
from ``law_info.content`` rows by the pure ``extract_references`` extractor.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..templating import templates as _templates
from ..deps import DbConn, get_db
from ..markdown_render import render_markdown
from ...eval.errors import NotFoundError
from ...eval.law_info import all_law_info, get_law_info, list_law_info_types
from ...eval.legal_refs import CATEGORY_ORDER, extract_references

router = APIRouter(tags=["law-info"])


@router.get("/law-info", include_in_schema=False, name="page_law_info")
def law_info_list(request: Request, db: DbConn = Depends(get_db)):
    types = list_law_info_types(db)
    return _templates.TemplateResponse(
        request, "law_info_list.html", {"types": types}
    )


@router.get("/law-info/{contract_type}", include_in_schema=False, name="page_law_info_detail")
def law_info_detail(request: Request, contract_type: str, db: DbConn = Depends(get_db)):
    try:
        info = get_law_info(contract_type, db)
    except NotFoundError:
        return _templates.TemplateResponse(
            request,
            "law_info_detail.html",
            {"not_found": True, "contract_type": contract_type, "info": None,
             "doubao_html": "", "deepseek_html": ""},
            status_code=404,
        )
    return _templates.TemplateResponse(
        request,
        "law_info_detail.html",
        {
            "not_found": False,
            "info": info,
            "doubao_html": render_markdown(info.get("doubao")),
            "deepseek_html": render_markdown(info.get("deepseek")),
        },
    )


@router.get("/law-references", include_in_schema=False, name="page_law_references")
def law_references(
    request: Request,
    db: DbConn = Depends(get_db),
    source: str = "",
    contract_type: str = "",
):
    items = all_law_info(db)
    refs = extract_references(items)
    # Apply filters.
    if source:
        refs = [r for r in refs if source in r["sources"]]
    if contract_type:
        refs = [r for r in refs if contract_type in r["contract_types"]]
    # Group by category (preserving CATEGORY_ORDER).
    grouped = [
        {"category": cat, "refs": [r for r in refs if r["category"] == cat]}
        for cat in CATEGORY_ORDER
    ]
    grouped = [g for g in grouped if g["refs"]]
    # Distinct contract types for the filter dropdown.
    all_types = sorted({i["contract_type"] for i in items})
    return _templates.TemplateResponse(
        request,
        "law_references.html",
        {
            "grouped": grouped,
            "total": len(refs),
            "source_filter": source,
            "type_filter": contract_type,
            "all_types": all_types,
        },
    )
