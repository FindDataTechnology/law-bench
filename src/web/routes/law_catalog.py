"""Law-catalog routes: ``/law-catalog/audit`` (引法审计总览) and
``/law-catalog/review`` (未解析名称复核队列).

Read-only pages compute live from ``law_catalog.clause_law_refs`` × the
replica; review actions only write the alias table (confirm → alias,
non-match → suppressed) and never touch clause bodies or ``law_refs``.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from ...law_catalog import audit as lc_audit
from ...law_catalog import store as lc_store
from ...contracts.templates import list_contract_types
from ..auth.deps import require_scope
from ..deps import DbConn, get_db
from ..templating import templates as _templates

read_only_router = APIRouter(tags=["law-catalog"])
write_router = APIRouter(tags=["law-catalog"])


def _zh_map() -> dict[str, str]:
    try:
        return {t["key"]: t["zh"] for t in list_contract_types()}
    except Exception:
        return {}


@read_only_router.get("/law-catalog/audit", include_in_schema=False, name="page_law_catalog_audit")
def law_catalog_audit(request: Request, db: DbConn = Depends(get_db)):
    result = lc_audit.collect_audit(db=db)
    # The overview page lists the two problem categories in full and links the
    # fallback work to the review queue; "ok" citations stay count-only.
    return _templates.TemplateResponse(
        request,
        "law_catalog_audit.html",
        {
            "result": result,
            "zh": _zh_map(),
        },
    )


@read_only_router.get("/law-catalog/review", include_in_schema=False, name="page_law_catalog_review")
def law_catalog_review(request: Request, db: DbConn = Depends(get_db)):
    pending = lc_store.distinct_unresolved(db=db)
    suggestions = {
        r["cited_name"]: lc_store.suggest_candidates(r["cited_name"], limit=3, db=db)
        for r in pending
    }
    suppressed = db.execute(
        "SELECT alias, created_at FROM law_catalog.aliases WHERE source = 'non_match' "
        "ORDER BY created_at DESC"
    ).fetchall()
    return _templates.TemplateResponse(
        request,
        "law_catalog_review.html",
        {
            "pending": pending,
            "suggestions": suggestions,
            "suppressed": suppressed,
        },
    )


@write_router.post(
    "/law-catalog/review/alias",
    include_in_schema=False,
    dependencies=[Depends(require_scope("content:write"))],
)
async def law_catalog_confirm_alias(request: Request, db: DbConn = Depends(get_db)):
    form = await request.form()
    alias = (form.get("alias") or "").strip()
    law_id = (form.get("law_id") or "").strip()
    if not alias or not law_id:
        raise HTTPException(status_code=400, detail="alias and law_id are required")
    law = lc_store.get_law(int(law_id), db=db)
    if not law:
        raise HTTPException(status_code=404, detail=f"law not found: {law_id}")
    lc_store.upsert_alias(alias, law["title"], law["id"], source="review", db=db)
    flash = quote(f"已确认别名：{alias} → {law['title']}")
    return RedirectResponse(f"/law-catalog/review?msg={flash}", status_code=303)


@write_router.post(
    "/law-catalog/review/non-match",
    include_in_schema=False,
    dependencies=[Depends(require_scope("content:write"))],
)
async def law_catalog_non_match(request: Request, db: DbConn = Depends(get_db)):
    form = await request.form()
    alias = (form.get("alias") or "").strip()
    if not alias:
        raise HTTPException(status_code=400, detail="alias is required")
    lc_store.upsert_alias(alias, None, None, source="non_match", db=db)
    return RedirectResponse(
        f"/law-catalog/review?msg={quote('已标记为不匹配（不再进入复核队列）')}",
        status_code=303,
    )


@read_only_router.get(
    "/law-catalog/revisions", include_in_schema=False, name="page_law_catalog_revisions"
)
def law_catalog_revisions(request: Request, db: DbConn = Depends(get_db), batch: str = ""):
    """Remediation revision records: evidence-chain view (read-only)."""
    if batch:
        rows = db.execute(
            "SELECT v.id, v.clause_id, v.contract_type, v.batch, v.cited_before, "
            "v.cited_after, v.disposition, v.rule_version, v.git_sha, v.applied_at, "
            "v.dead_law_id, v.successor_law_id, v.authority_law_id, "
            "ld.title AS dead_title, ld.status AS dead_status, ls.title AS successor_title, "
            "ls.status AS successor_status, la.title AS authority_title "
            "FROM law_catalog.citation_revisions v "
            "LEFT JOIN law_catalog.laws ld ON ld.id = v.dead_law_id "
            "LEFT JOIN law_catalog.laws ls ON ls.id = v.successor_law_id "
            "LEFT JOIN law_catalog.laws la ON la.id = v.authority_law_id "
            "WHERE v.batch = %s ORDER BY v.id DESC LIMIT 500",
            (batch,),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT v.id, v.clause_id, v.contract_type, v.batch, v.cited_before, "
            "v.cited_after, v.disposition, v.rule_version, v.git_sha, v.applied_at, "
            "v.dead_law_id, v.successor_law_id, v.authority_law_id, "
            "ld.title AS dead_title, ld.status AS dead_status, ls.title AS successor_title, "
            "ls.status AS successor_status, la.title AS authority_title "
            "FROM law_catalog.citation_revisions v "
            "LEFT JOIN law_catalog.laws ld ON ld.id = v.dead_law_id "
            "LEFT JOIN law_catalog.laws ls ON ls.id = v.successor_law_id "
            "LEFT JOIN law_catalog.laws la ON la.id = v.authority_law_id "
            "ORDER BY v.id DESC LIMIT 500"
        ).fetchall()
    batches = db.execute(
        "SELECT batch, count(*) n FROM law_catalog.citation_revisions GROUP BY 1 ORDER BY 1"
    ).fetchall()
    return _templates.TemplateResponse(
        request,
        "law_catalog_revisions.html",
        {"rows": rows, "batches": batches, "batch": batch, "zh": _zh_map()},
    )

router = APIRouter(tags=["law-catalog"])
router.include_router(read_only_router)
router.include_router(write_router)
