"""``/samples`` — browse-and-download UI over the MinIO artifact corpus.

Server-rendered HTML page (Jinja2) listing every stored
``contract_artifacts`` row in a paginated table with type -> scenario ->
stance cascading filters and direct DOCX/PDF download anchors. No slot
filling, no generation triggers — this is a thin read layer over
:mod:`src.contracts.artifacts`.

Mirrors the conventions in :mod:`src.web.routes.pages` /
:mod:`src.web.routes.contracts`: ``Request``-based handler,
``_templates.TemplateResponse``, ``DbConn = Depends(get_db)``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from ..deps import DbConn, get_db
from ..templating import templates as _templates
from ...contracts import list_contract_types
from ...contracts.artifacts import (
    distinct_scenarios,
    distinct_stances,
    list_samples,
)

router = APIRouter(tags=["samples"])


def _clean(value: str | None) -> str | None:
    """Treat an empty string (the "全部" option) as no filter."""
    return value or None


@router.get("/samples", include_in_schema=False, name="page_samples")
def page_samples(
    request: Request,
    contract_type: str | None = Query(None),
    scenario: str | None = Query(None),
    stance: str | None = Query(None),
    include_history: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: DbConn = Depends(get_db),
):
    """Render the samples library page.

    Query params drive both the filter form's selected state and the
    ``list_samples`` query. ``contract_type`` is required-by-UX to populate
    the scenario/stance dropdowns; without it those dropdowns show only the
    "全部" option and the table lists artifacts across all types.
    ``include_history`` shows superseded (old body) rows alongside current
    ones — they are hidden by default so the page surfaces only the latest
    body per natural key.
    """
    contract_type = _clean(contract_type)
    scenario = _clean(scenario)
    stance = _clean(stance)

    all_types = list_contract_types()  # [{key, zh}, ...] — file-backed, no DB
    # key -> Chinese name, so the table shows 买卖合同 instead of the raw English
    # key "sale" (consistent with the dropdown, which already renders zh).
    type_map = {ct["key"]: ct["zh"] for ct in all_types}

    scen_opts: list[str] = []
    stance_opts: list[str] = []
    if contract_type:
        scen_opts = distinct_scenarios(
            contract_type, include_superseded=include_history, db=db
        )
        stance_opts = distinct_stances(
            contract_type, include_superseded=include_history, db=db
        )

    rows, total = list_samples(
        contract_type,
        scenario,
        stance,
        limit,
        offset,
        db=db,
        include_superseded=include_history,
    )

    page = (offset // limit) + 1
    pages = (total + limit - 1) // limit if total else 1

    return _templates.TemplateResponse(
        request,
        "samples.html",
        {
            "all_types": all_types,
            "type_map": type_map,
            "artifacts": rows,
            "total": total,
            "limit": limit,
            "offset": offset,
            "page": page,
            "pages": pages,
            "has_next": offset + limit < total,
            "has_prev": offset > 0,
            "selected_ct": contract_type,
            "selected_scenario": scenario,
            "selected_stance": stance,
            "scen_opts": scen_opts,
            "stance_opts": stance_opts,
            "include_history": include_history,
        },
    )
