"""HTML routes for the evaluation-rules management UI.

Server-rendered with Jinja2. Writes delegate to ``src/eval/manage.py`` (which
raises ``ManageError`` subclasses). For HTML flows we catch those and redirect
back with an error flash rather than returning JSON, so the browser UX stays
friendly; the JSON API under ``/api`` is the scriptable alternative. Each
handler takes a ``db`` dependency (see ``src/web/deps.py``) so tests can point
the layer at a throwaway DB.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from src.eval import manage as M
from src.eval.manage import ManageError
from src.eval.store import list_compares

from ..templating import templates as _templates
from ..auth.deps import require_scope
from ..deps import DbConn, get_db
from .api import run_harbor_extraction

router = APIRouter(tags=["pages"])


def _flash(
    path: str, msg: str, err: bool = False, status: int = 303, **interp
) -> RedirectResponse:
    """Redirect with a flash message.

    ``msg`` is normally a dotted catalog key (e.g. ``"flash.rubric_created"``)
    resolved against the active locale by ``base.html``'s ``tr`` helper; any
    ``**interp`` values are appended as extra query params so interpolated
    flashes (``name``, ``detail``) stay locale-independent in the URL. A raw
    string (not a key) passes through unchanged for dynamic error text.
    """
    sep = "&" if "?" in path else "?"
    q = f"msg={quote(msg)}"
    if err:
        q += "&err=1"
    for key, val in interp.items():
        q += f"&{key}={quote(str(val))}"
    return RedirectResponse(f"{path}{sep}{q}", status_code=status)


# --- read ------------------------------------------------------------------ #


@router.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse(url="/rubrics")


@router.get("/rubrics", include_in_schema=False, name="page_list_rubrics")
def list_rubrics(request: Request, db: DbConn = Depends(get_db)):
    return _templates.TemplateResponse(
        request, "rubrics_list.html", {"rubrics": M.list_rubrics_with_counts(db_path=db)}
    )


@router.get("/rubrics/new", include_in_schema=False, name="page_new_rubric")
def new_rubric(request: Request):
    # Must be defined before /rubrics/{name} so "new" is not captured as a name.
    return _templates.TemplateResponse(
        request, "rubric_form.html", {"mode": "create", "rubric": None}
    )


@router.get("/rubrics/{name}", include_in_schema=False, name="page_rubric_detail")
def rubric_detail(request: Request, name: str, db: DbConn = Depends(get_db)):
    return _templates.TemplateResponse(
        request, "rubric_detail.html", {"rubric": M.get_rubric_detail(name, db_path=db)}
    )


@router.get("/rubrics/{name}/edit", include_in_schema=False, name="page_edit_rubric")
def edit_rubric(request: Request, name: str, db: DbConn = Depends(get_db)):
    return _templates.TemplateResponse(
        request, "rubric_form.html", {"mode": "edit", "rubric": M.get_rubric_detail(name, db_path=db)}
    )


# --- rubric writes --------------------------------------------------------- #


@router.post(
    "/rubrics",
    include_in_schema=False,
    name="page_create_rubric",
    dependencies=[Depends(require_scope("content:write"))],
)
async def create_rubric(request: Request, db: DbConn = Depends(get_db)):
    form = await request.form()
    name = form.get("name", "")
    context = form.get("context", "")
    description = form.get("description") or None
    criteria = _collect_criteria(form)
    try:
        created = M.create_rubric(name, context, description, criteria, db_path=db)
    except ManageError as exc:
        return _flash("/rubrics/new", str(exc), err=True)
    return _flash(f"/rubrics/{quote(created['name'])}", "flash.rubric_created")


@router.post(
    "/rubrics/{name}",
    include_in_schema=False,
    name="page_update_rubric",
    dependencies=[Depends(require_scope("content:write"))],
)
async def update_rubric(request: Request, name: str, db: DbConn = Depends(get_db)):
    form = await request.form()
    try:
        detail = M.get_rubric_detail(name, db_path=db)
        updated = M.update_rubric(
            detail["id"],
            form.get("name", ""),
            form.get("context", ""),
            form.get("description") or None,
            db_path=db,
        )
    except ManageError as exc:
        return _flash(f"/rubrics/{quote(name)}/edit", str(exc), err=True)
    return _flash(f"/rubrics/{quote(updated['name'])}", "flash.rubric_updated")


@router.post(
    "/rubrics/{name}/delete",
    include_in_schema=False,
    name="page_delete_rubric",
    dependencies=[Depends(require_scope("admin"))],
)
async def delete_rubric(request: Request, name: str, db: DbConn = Depends(get_db)):
    try:
        detail = M.get_rubric_detail(name, db_path=db)
        M.delete_rubric(detail["id"], db_path=db)
    except ManageError as exc:
        return _flash("/rubrics", str(exc), err=True)
    return _flash("/rubrics", "flash.rubric_deleted", name=name)


# --- criterion writes ------------------------------------------------------ #


@router.post(
    "/rubrics/{name}/criteria",
    include_in_schema=False,
    name="page_add_criterion",
    dependencies=[Depends(require_scope("content:write"))],
)
async def add_criterion(request: Request, name: str, db: DbConn = Depends(get_db)):
    form = await request.form()
    try:
        detail = M.get_rubric_detail(name, db_path=db)
        M.add_criterion(
            detail["id"], form.get("name", ""), form.get("description", ""), form.get("guidance", ""),
            db_path=db,
        )
    except ManageError as exc:
        return _flash(f"/rubrics/{quote(name)}", str(exc), err=True)
    return _flash(f"/rubrics/{quote(name)}", "flash.criterion_added")


@router.post(
    "/rubrics/{name}/criteria/{cid}",
    include_in_schema=False,
    name="page_update_criterion",
    dependencies=[Depends(require_scope("content:write"))],
)
async def update_criterion(request: Request, name: str, cid: int, db: DbConn = Depends(get_db)):
    form = await request.form()
    try:
        M.update_criterion(
            cid, form.get("name", ""), form.get("description", ""), form.get("guidance", ""),
            db_path=db,
        )
    except ManageError as exc:
        return _flash(f"/rubrics/{quote(name)}", str(exc), err=True)
    return _flash(f"/rubrics/{quote(name)}", "flash.criterion_updated")


@router.post(
    "/rubrics/{name}/criteria/{cid}/delete",
    include_in_schema=False,
    name="page_delete_criterion",
    dependencies=[Depends(require_scope("admin"))],
)
async def delete_criterion(request: Request, name: str, cid: int, db: DbConn = Depends(get_db)):
    try:
        M.delete_criterion(cid, db_path=db)
    except ManageError as exc:
        return _flash(f"/rubrics/{quote(name)}", str(exc), err=True)
    return _flash(f"/rubrics/{quote(name)}", "flash.criterion_deleted")


@router.post(
    "/rubrics/{name}/criteria/{cid}/move",
    include_in_schema=False,
    name="page_move_criterion",
    dependencies=[Depends(require_scope("content:write"))],
)
async def move_criterion(request: Request, name: str, cid: int, db: DbConn = Depends(get_db)):
    form = await request.form()
    direction = form.get("direction", "")
    try:
        detail = M.get_rubric_detail(name, db_path=db)
        ids = [c["id"] for c in detail["criteria"]]
        idx = ids.index(cid)
        if direction == "up" and idx > 0:
            ids[idx - 1], ids[idx] = ids[idx], ids[idx - 1]
        elif direction == "down" and idx < len(ids) - 1:
            ids[idx + 1], ids[idx] = ids[idx], ids[idx + 1]
        M.reorder_criteria(detail["id"], ids, db_path=db)
    except (ManageError, ValueError) as exc:
        return _flash(f"/rubrics/{quote(name)}", str(exc), err=True)
    return _flash(f"/rubrics/{quote(name)}", "flash.criterion_moved")


# --- prompts (read) -------------------------------------------------------- #


@router.get("/prompts", include_in_schema=False, name="page_list_prompts")
def list_prompts(request: Request, db: DbConn = Depends(get_db)):
    return _templates.TemplateResponse(
        request, "prompts_list.html", {"prompts": M.list_prompts(db_path=db)}
    )


@router.get("/prompts/new", include_in_schema=False, name="page_new_prompt")
def new_prompt(request: Request):
    # Defined before /prompts/{name} so "new" is not captured as a name.
    return _templates.TemplateResponse(
        request, "prompt_form.html", {"mode": "create", "prompt": None}
    )


@router.get("/prompts/{name}", include_in_schema=False, name="page_prompt_detail")
def prompt_detail(request: Request, name: str, db: DbConn = Depends(get_db)):
    return _templates.TemplateResponse(
        request, "prompt_detail.html", {"prompt": M.get_prompt(name, db_path=db)}
    )


@router.get("/prompts/{name}/edit", include_in_schema=False, name="page_edit_prompt")
def edit_prompt(request: Request, name: str, db: DbConn = Depends(get_db)):
    return _templates.TemplateResponse(
        request, "prompt_form.html", {"mode": "edit", "prompt": M.get_prompt(name, db_path=db)}
    )


# --- prompts (writes) ------------------------------------------------------ #


@router.post(
    "/prompts",
    include_in_schema=False,
    name="page_create_prompt",
    dependencies=[Depends(require_scope("content:write"))],
)
async def create_prompt(request: Request, db: DbConn = Depends(get_db)):
    form = await request.form()
    try:
        created = M.create_prompt(
            form.get("name", ""),
            form.get("contract_type", ""),
            form.get("purpose", ""),
            form.get("content", ""),
            form.get("description") or None,
            form.get("prompt_type") or None,
            db_path=db,
        )
    except ManageError as exc:
        return _flash("/prompts/new", str(exc), err=True)
    return _flash(f"/prompts/{quote(created['name'])}", "flash.prompt_created")


@router.post(
    "/prompts/{name}",
    include_in_schema=False,
    name="page_update_prompt",
    dependencies=[Depends(require_scope("content:write"))],
)
async def update_prompt(request: Request, name: str, db: DbConn = Depends(get_db)):
    form = await request.form()
    try:
        detail = M.get_prompt(name, db_path=db)
        updated = M.update_prompt(
            detail["id"],
            form.get("name", ""),
            form.get("contract_type", ""),
            form.get("purpose", ""),
            form.get("content", ""),
            form.get("description") or None,
            form.get("prompt_type") or None,
            db_path=db,
        )
    except ManageError as exc:
        return _flash(f"/prompts/{quote(name)}/edit", str(exc), err=True)
    return _flash(f"/prompts/{quote(updated['name'])}", "flash.prompt_updated")


@router.post(
    "/prompts/{name}/delete",
    include_in_schema=False,
    name="page_delete_prompt",
    dependencies=[Depends(require_scope("admin"))],
)
async def delete_prompt(request: Request, name: str, db: DbConn = Depends(get_db)):
    try:
        detail = M.get_prompt(name, db_path=db)
        M.delete_prompt(detail["id"], db_path=db)
    except ManageError as exc:
        return _flash("/prompts", str(exc), err=True)
    return _flash("/prompts", "flash.prompt_deleted", name=name)


# --- harbor re-extraction -------------------------------------------------- #


@router.post(
    "/harbor/extract",
    include_in_schema=False,
    name="page_harbor_extract",
    dependencies=[Depends(require_scope("admin"))],
)
async def harbor_extract(request: Request):
    # ``run_harbor_extraction`` shells out to the harbor script with a ``--db``
    # file path; it must NOT receive the borrowed Postgres connection (str() of
    # a connection is a repr, not a path). It falls back to DEFAULT_DB.
    code, _out, err = run_harbor_extraction()
    if code != 0:
        return _flash("/rubrics", "flash.harbor_failed", err=True, detail=(err or '').strip())
    return _flash("/rubrics", "flash.harbor_refreshed")


# --- compare --------------------------------------------------------------- #


@router.get("/compare", include_in_schema=False, name="page_list_compares")
def list_compares_page(request: Request, db: DbConn = Depends(get_db)):
    return _templates.TemplateResponse(
        request, "compare_list.html", {"compares": list_compares(db_path=db)}
    )


@router.get("/compare/new", include_in_schema=False, name="page_new_compare")
def new_compare(request: Request, db: DbConn = Depends(get_db)):
    # Defined before /compare/{id} so "new" is not captured as an id.
    prompts = M.list_prompts(db_path=db)
    return _templates.TemplateResponse(
        request,
        "compare_form.html",
        {
            "prompts": prompts,
            "rubrics": M.list_rubrics_with_counts(db_path=db),
            # Known contract types (from prompts that exist) feed the
            # contract_type datalist suggestions on the build form.
            "contract_types": sorted(
                {p["contract_type"] for p in prompts if p.get("contract_type")}
            ),
        },
    )


@router.get("/compare/{compare_id}", include_in_schema=False, name="page_compare_detail")
def compare_detail(request: Request, compare_id: int, db: DbConn = Depends(get_db)):
    # The matrix is rendered client-side by app.js (localStorage mirror +
    # reconcile with /api/compare/{id}); the page is a shell carrying the id.
    return _templates.TemplateResponse(
        request, "compare_detail.html", {"compare_id": compare_id}
    )


# --- helpers --------------------------------------------------------------- #


def _collect_criteria(form) -> list[dict]:
    """Zip the repeated criteria_name/description/guidance fields into dicts.

    Rows with an empty name are skipped. Field order is preserved across the
    three getlist calls because each criterion row renders its three inputs
    contiguously in DOM order.
    """
    names = form.getlist("criteria_name")
    descs = form.getlist("criteria_description")
    guids = form.getlist("criteria_guidance")
    criteria = []
    for n, d, g in zip(names, descs, guids):
        if (n or "").strip():
            criteria.append({"name": n, "description": d, "guidance": g})
    return criteria
