"""Clause routes: browse/search, corpus extraction, assembly download, and the
CRUD management dashboard (create / edit / delete clauses).

Backed by the ``clauses`` table (Postgres) via :mod:`src.clauses`. Assembly
reuses the ``document-generation`` renderer so slots stay fillable. Dashboard
writes (create/update) set ``manual=true`` so re-extraction preserves them.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse

from ..templating import templates as _templates
from ..auth.deps import require_scope
from ..deps import DbConn, get_db
from ..markdown_render import render_markdown
from ...clauses import generate_contract_assembled, list_clauses, tag_vocab_for_type
from ...clauses.store import (
    count_clauses,
    counts_by_type,
    create_clause,
    delete_clause,
    get_custom_clause,
    search_clauses,
    update_clause,
)
from ...clauses.tag_review import bulk_review, list_pending, review_tag
from ...contracts import list_contract_types
from ...generator import ConverterNotAvailableError
from ...eval.errors import NotFoundError

# The router is split into a read-only surface (GET browse/search/generate pages)
# and a write surface (POST CRUD: extract/create/update/delete/review) so the
# public pod (``create_public_app``) can mount only ``read_only_router`` and
# exclude the management write routes (design D2: behavior-preserving split —
# the origin includes both). Both sub-routers carry no prefix and the
# ``clauses`` tag so the origin's OpenAPI shape is unchanged.
read_only_router = APIRouter(tags=["clauses"])
write_router = APIRouter(tags=["clauses"])

# Backward-compat alias ``router`` is assembled at the END of this module
# (after every route decorator) because ``include_router`` snapshots the
# sub-routers' route lists at call time — building the parent here, before
# the decorators run, would copy empty lists and the origin would 404 on
# every ``/clauses`` path. See ``router`` at the file bottom.

_EXTRACT_MAX_LIMIT = 50
_CATEGORIES = ("base", "tagged", "custom")
_CATEGORY_ZH = {"base": "基本（全国）", "tagged": "标签（地域）", "custom": "自定义"}
def _tags_from_query(request: Request, contract_type: str | None = None) -> dict:
    """Collect tag dims present in the query string into a {dim: value} dict."""
    out: dict[str, str] = {}
    for dim in tag_vocab_for_type(contract_type):
        v = request.query_params.get(dim)
        if v:
            out[dim] = v
    return out


def _tags_from_form(form, contract_type: str | None = None) -> dict:
    """Collect tag dims posted from a form (empty values omitted).

    Controlled dims (including ``scenario``) come from their dropdowns, which
    are rendered from ``tag_vocab_for_type``.
    """
    out: dict[str, str] = {}
    for dim in tag_vocab_for_type(contract_type):
        v = (form.get(dim) or "").strip()
        if v:
            out[dim] = v
    return out


def _edit_tag_dims(clause: dict | None) -> list[str]:
    """Tag dims to render as dropdowns on the edit form: all dims valid for the
    clause's contract type (universal + type-specific)."""
    ct = (clause or {}).get("contract_type")
    return list(tag_vocab_for_type(ct).keys())


def _zh_map() -> dict:
    return {t["key"]: t["zh"] for t in list_contract_types()}


def _type_rows(db: DbConn) -> list[dict]:
    zh = _zh_map()
    return [
        {
            "contract_type": r["contract_type"],
            "zh": zh.get(r["contract_type"], r["contract_type"]),
            "base": r["base"],
            "tagged": r["tagged"],
            "custom": r["custom"],
            "scenarios": r["scenarios"],
        }
        for r in counts_by_type(db)
    ]


@read_only_router.get("/clauses", include_in_schema=False, name="page_clauses")
def clauses_list(request: Request, q: str = "", db: DbConn = Depends(get_db)):
    counts = count_clauses(db)
    tags = _tags_from_query(request)
    results = search_clauses(q, tags=tags or None, db=db) if (q or tags) else None
    return _templates.TemplateResponse(
        request,
        "clauses_list.html",
        {
            "counts": counts,
            "rows": _type_rows(db),
            "flash": request.query_params.get("flash"),
            "q": q,
            "results": results,
            "zh": _zh_map(),
            "tag_filters": list(tag_vocab_for_type(None).keys()),
            "tag_vocab": tag_vocab_for_type(None),
            "active_tags": tags,
        },
    )


@write_router.post(
    "/clauses/extract",
    include_in_schema=False,
    name="page_clauses_extract",
    dependencies=[Depends(require_scope("admin"))],
)
def clauses_extract(request: Request, limit: int = 5):
    """Trigger a small resumable extraction batch (full runs use the CLI)."""
    from src.clauses.cli import run_extraction

    limit = max(0, min(limit, _EXTRACT_MAX_LIMIT))
    try:
        summary = run_extraction(limit=limit)
        flash = (
            f"抽取完成：新增 {summary['done']} 份，跳过 {summary['skipped']} 份，"
            f"失败 {summary['failed']} 份，共 {summary['clauses']} 条条款。"
        )
    except Exception as exc:  # noqa: BLE001
        flash = f"抽取失败：{exc}"
    # run_extraction writes via its own connection; read fresh counts to render.
    db = None
    return _templates.TemplateResponse(
        request,
        "clauses_list.html",
        {
            "counts": count_clauses(db),
            "rows": _type_rows(db),
            "flash": flash,
            "q": "",
            "results": None,
            "zh": _zh_map(),
        },
    )


@read_only_router.get(
    "/clauses/{contract_type}/generate",
    include_in_schema=False,
    name="page_clauses_generate",
)
def clauses_generate(
    contract_type: str,
    format: str = "pdf",
    scenario: str | None = None,
    stance: str | None = None,
    db: DbConn = Depends(get_db),
):
    if format not in ("docx", "pdf"):
        raise HTTPException(status_code=400, detail="unsupported format; use docx or pdf")
    try:
        result = generate_contract_assembled(
            contract_type, scenario=scenario or None, stance=stance or None, format=format, db=db
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"unknown contract type: {contract_type}")
    except ConverterNotAvailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    path = result["docx_path"] if format == "docx" else result["pdf_path"]
    if path is None:
        raise HTTPException(status_code=500, detail="document generation failed")
    media = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if format == "docx"
        else "application/pdf"
    )
    return FileResponse(path, media_type=media, filename=f"{contract_type}.{format}")


# --- management dashboard (CRUD) ------------------------------------------- #


@read_only_router.get(
    "/clauses/{contract_type}/new",
    include_in_schema=False,
    name="page_clauses_new",
)
def clauses_new(request: Request, contract_type: str):
    zh = _zh_map()
    if contract_type not in zh:
        raise HTTPException(status_code=404, detail=f"unknown contract type: {contract_type}")
    return _templates.TemplateResponse(
        request,
        "clause_new.html",
        {
            "contract_type": contract_type,
            "zh": zh[contract_type],
            "categories": _CATEGORIES,
            "category_zh": _CATEGORY_ZH,
            "tag_filters": list(tag_vocab_for_type(contract_type).keys()),
            "tag_vocab": tag_vocab_for_type(contract_type),
        },
    )


@write_router.post(
    "/clauses/{contract_type}/new",
    include_in_schema=False,
    dependencies=[Depends(require_scope("content:write"))],
)
async def clauses_create(request: Request, contract_type: str, db: DbConn = Depends(get_db)):
    form = await request.form()
    category = form.get("category", "custom") or "custom"
    if category not in _CATEGORIES:
        category = "custom"
    create_clause(
        {
            "contract_type": contract_type,
            "category": category,
            "section": (form.get("section") or "附则").strip(),
            "body": form.get("body") or "",
            "tags": _tags_from_form(form, contract_type),
        },
        db=db,
    )
    return RedirectResponse(
        f"/clauses/{contract_type}?flash={quote('已创建条款')}", status_code=303
    )


@read_only_router.get(
    "/clauses/{contract_type}/clauses/{clause_id}",
    include_in_schema=False,
    name="page_clauses_edit",
)
def clauses_edit(request: Request, contract_type: str, clause_id: int, db: DbConn = Depends(get_db)):
    zh = _zh_map()
    if contract_type not in zh:
        raise HTTPException(status_code=404, detail=f"unknown contract type: {contract_type}")
    clause = get_custom_clause(clause_id, db=db)
    if clause is None:
        raise HTTPException(status_code=404, detail=f"clause not found: {clause_id}")
    return _templates.TemplateResponse(
        request,
        "clause_edit.html",
        {
            "contract_type": contract_type,
            "zh": zh[contract_type],
            "clause": clause,
            "body_html": render_markdown(clause["body"]),
            "categories": _CATEGORIES,
            "category_zh": _CATEGORY_ZH,
            "tag_dims": _edit_tag_dims(clause),
            "tag_vocab": tag_vocab_for_type(contract_type),
        },
    )


@write_router.post(
    "/clauses/{contract_type}/clauses/{clause_id}",
    include_in_schema=False,
    dependencies=[Depends(require_scope("content:write"))],
)
async def clauses_update(request: Request, contract_type: str, clause_id: int, db: DbConn = Depends(get_db)):
    form = await request.form()
    category = form.get("category") or "custom"
    if category not in _CATEGORIES:
        category = "custom"
    try:
        update_clause(
            clause_id,
            {
                "section": (form.get("section") or "附则").strip(),
                "body": form.get("body") or "",
                "category": category,
                "tags": _tags_from_form(form, contract_type),
            },
            db=db,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"clause not found: {clause_id}")
    return RedirectResponse(
        f"/clauses/{contract_type}?flash={quote('已更新条款')}", status_code=303
    )


@write_router.post(
    "/clauses/{contract_type}/clauses/{clause_id}/delete",
    include_in_schema=False,
    name="page_clauses_delete",
    dependencies=[Depends(require_scope("admin"))],
)
async def clauses_delete_route(contract_type: str, clause_id: int, db: DbConn = Depends(get_db)):
    try:
        delete_clause(clause_id, db=db)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"clause not found: {clause_id}")
    return RedirectResponse(
        f"/clauses/{contract_type}?flash={quote('已删除条款')}", status_code=303
    )


# --- tag review ----------------------------------------------------------- #


@read_only_router.get("/clauses/review", include_in_schema=False, name="page_clauses_review")
def clauses_review(request: Request, db: DbConn = Depends(get_db)):
    pending = list_pending(db=db)
    return _templates.TemplateResponse(
        request,
        "clauses_review.html",
        {"pending": pending, "zh": _zh_map()},
    )


@write_router.post(
    "/clauses/{contract_type}/clauses/{clause_id}/review",
    include_in_schema=False,
    dependencies=[Depends(require_scope("content:write"))],
)
async def clauses_review_tag_route(
    request: Request, contract_type: str, clause_id: int, db: DbConn = Depends(get_db)
):
    form = await request.form()
    dim = (form.get("dim") or "").strip()
    status = (form.get("status") or "").strip()
    if dim and status:
        try:
            review_tag(clause_id, dim, status, db=db)
        except NotFoundError:
            raise HTTPException(status_code=404, detail=f"clause not found: {clause_id}")
    return RedirectResponse(
        f"/clauses/{contract_type}/clauses/{clause_id}?flash={quote('已审核标签')}",
        status_code=303,
    )


@write_router.post(
    "/clauses/{contract_type}/clauses/{clause_id}/review-all",
    include_in_schema=False,
    dependencies=[Depends(require_scope("content:write"))],
)
async def clauses_review_all_route(
    request: Request, contract_type: str, clause_id: int, db: DbConn = Depends(get_db)
):
    form = await request.form()
    status = (form.get("status") or "approved").strip()
    try:
        bulk_review(clause_id, status, db=db)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"clause not found: {clause_id}")
    return RedirectResponse(
        f"/clauses/{contract_type}/clauses/{clause_id}?flash={quote('已批量审核')}",
        status_code=303,
    )


@read_only_router.get(
    "/clauses/{contract_type}",
    include_in_schema=False,
    name="page_clauses_detail",
)
def clauses_detail(
    request: Request,
    contract_type: str,
    scenario: str = "",
    category: str = "",
    q: str = "",
    db: DbConn = Depends(get_db),
):
    zh = _zh_map()
    if contract_type not in zh:
        return _templates.TemplateResponse(
            request,
            "clauses_detail.html",
            {"not_found": True, "contract_type": contract_type, "zh": contract_type,
             "grouped": [], "scenarios": [], "scenario_filter": "", "category_filter": "",
             "q": "", "flash": None},
            status_code=404,
        )
    detail_tags = _tags_from_query(request, contract_type)
    if scenario:
        detail_tags["scenario"] = scenario
    clauses = list_clauses(
        contract_type,
        category=category or None,
        q=q or None,
        tags=detail_tags or None,
        db=db,
    )
    all_for_type = list_clauses(contract_type, db=db)
    scenarios = sorted({c.get("tags", {}).get("scenario") for c in all_for_type if c.get("tags", {}).get("scenario")})
    from ...clauses.extract import SECTION_ORDER, section_rank

    sections: list[tuple[str, list]] = []
    index: dict[str, int] = {}
    for c in clauses:
        if c["section"] not in index:
            index[c["section"]] = len(sections)
            sections.append((c["section"], []))
        sections[index[c["section"]]][1].append(c)
    sections.sort(key=lambda s: section_rank(s[0]))
    grouped = [
        {
            "section": s,
            "clauses": [{**c, "body_html": render_markdown(c["body"])} for c in cs],
        }
        for s, cs in sections
    ]
    return _templates.TemplateResponse(
        request,
        "clauses_detail.html",
        {
            "not_found": False,
            "contract_type": contract_type,
            "zh": zh[contract_type],
            "grouped": grouped,
            "scenarios": scenarios,
            "scenario_filter": scenario,
            "category_filter": category,
            "q": q,
            "flash": request.query_params.get("flash"),
            "section_order": SECTION_ORDER,
            "tag_filters": list(tag_vocab_for_type(contract_type).keys()),
            "tag_vocab": tag_vocab_for_type(contract_type),
            "active_tags": _tags_from_query(request, contract_type),
        },
    )


# --------------------------------------------------------------------------- #
# Backward-compat alias: assemble the parent ``router`` HERE, at module bottom,
# AFTER every ``@read_only_router`` / ``@write_router`` decorator above has
# registered its route. ``APIRouter.include_router`` copies the sub-router's
# route list at call time — building the parent before the decorators run would
# copy empty lists and the origin would 404 on every ``/clauses`` path.
router = APIRouter(tags=["clauses"])
router.include_router(read_only_router)
router.include_router(write_router)
