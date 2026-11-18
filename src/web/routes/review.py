"""Human-review routes over eval verdicts (change add-web-human-review).

Two page routes and one decision POST. Every route inherits the app-level
``get_current_user`` dependency (see ``create_app``), so an anonymous browser
navigation 302s to ``/auth/login``; the decision POST additionally requires the
``review:annotate`` scope, which Logto bundles into the ``lawbench-annotator``
role. The annotator stamp is always the session identity — never a form field.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..auth.deps import User, get_current_user, require_scope
from ..deps import DbConn, get_db
from ..templating import templates as _templates
from ...eval import review as review_store
from ...eval.errors import NotFoundError

read_only_router = APIRouter(tags=["review"])
write_router = APIRouter(tags=["review"])

REVIEW_SCOPE = "review:annotate"


def _annotator_of(user: User) -> str:
    """Stable, readable annotator stamp from the session identity.

    Logto's ``sub`` is the stable id, but it is opaque in reports; the account
    email (or display name) is what an operator recognises. Falls back to
    ``sub`` when neither is present, so a stamp always exists.
    """
    return user.email or user.name or user.sub


@read_only_router.get("/review", include_in_schema=False, name="page_review")
def review_home(
    request: Request,
    batch: str | None = None,
    user: User = Depends(get_current_user),
    db: DbConn = Depends(get_db),
):
    """Batch overview plus the caller's pending queue.

    Any authenticated caller may look; only decisions carry the scope check
    (``require_scope`` on the POST), so the resolved :class:`User` is taken
    straight from ``get_current_user`` rather than through a scope gate.
    """
    batches = review_store.list_batches(db=db)
    selected = batch or (batches[0]["batch_id"] if batches else None)
    tasks = (
        review_store.list_tasks(
            batch_id=selected, status="pending",
            for_annotator=_annotator_of(user), db=db,
        )
        if selected
        else []
    )
    return _templates.TemplateResponse(
        request,
        "review_list.html",
        {
            "batches": batches,
            "selected": selected,
            "tasks": tasks,
            "me": _annotator_of(user),
        },
    )


@read_only_router.get(
    "/review/{task_id}", include_in_schema=False, name="page_review_task"
)
def review_task(
    request: Request,
    task_id: int,
    user: User = Depends(get_current_user),
    db: DbConn = Depends(get_db),
):
    try:
        task = review_store.get_task_detail(task_id, db=db)
    except NotFoundError:
        return _templates.TemplateResponse(
            request, "review_task.html", {"task": None, "task_id": task_id},
            status_code=404,
        )
    # Queue position context for the pending page (spec: Queue Position
    # Indicator). Computed against the *annotator's own* pending queue — the
    # same exclusion list_tasks applies post-decide — so the indicator and the
    # decide-redirect below can never disagree. Tasks outside that queue (e.g.
    # a sibling slot this annotator already decided) and already-decided tasks
    # get no indicator.
    pending_ids = None
    if task["status"] == "pending":
        mine = review_store.list_tasks(
            batch_id=task["batch_id"], status="pending",
            for_annotator=_annotator_of(user), db=db,
        )
        ids = [t["id"] for t in mine]
        if task_id in ids:
            pending_ids = ids
    return _templates.TemplateResponse(
        request,
        "review_task.html",
        {
            "task": task,
            "me": _annotator_of(user),
            "pending_ids": pending_ids,
        },
    )


@write_router.post(
    "/review/{task_id}/decide",
    include_in_schema=False,
    name="page_review_decide",
)
async def review_decide(
    request: Request,
    task_id: int,
    user: User = Depends(require_scope(REVIEW_SCOPE)),
    db: DbConn = Depends(get_db),
):
    form = await request.form()
    verdict = (form.get("verdict") or "").strip()
    note = (form.get("note") or "").strip()
    try:
        outcome = review_store.decide_task(
            task_id=task_id,
            annotator=_annotator_of(user),
            verdict=verdict,
            note=note,
            db=db,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"review task not found: {task_id}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not outcome["ok"]:
        return RedirectResponse(
            f"/review/{task_id}?flash=review.msg_conflict",
            status_code=303,
        )
    # Momentum flow (spec: Decision Flow Continuation): land the annotator on
    # their next pending task in the same batch instead of the list; only a
    # drained queue falls back to the batch view. ``msg`` rides base.html's
    # ok-flash and is a catalog key, so it renders in the active locale; the
    # conflict path above keeps the task page's error ``flash`` (also a key).
    batch_id = outcome["task"]["batch_id"]
    remaining = review_store.list_tasks(
        batch_id=batch_id, status="pending",
        for_annotator=_annotator_of(user), db=db,
    )
    if remaining:
        next_id = remaining[0]["id"]
        return RedirectResponse(
            f"/review/{next_id}?msg=review.msg_recorded",
            status_code=303,
        )
    return RedirectResponse(
        f"/review?batch={quote(batch_id)}&msg=review.msg_queue_done",
        status_code=303,
    )


router = APIRouter(tags=["review"])
router.include_router(read_only_router)
router.include_router(write_router)
