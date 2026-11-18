"""Domain workbench: the expert authoring surface (change
``add-expert-authoring-surface``, design D4/D5).

Server-rendered Jinja following the ``admin.py`` flash+redirect pattern. This
is the MEMBER gate (not the admin gate): every route composes the two C1 gates
in order — platform scope first (``require_scope``, Logto is the only source of
platform roles) then domain role (``require_domain_role``, the workspace
membership record is the only source of domain roles; admins bypass the domain
check):

- workbench READ  (browse / unit detail / events)         — ``content:read`` AND domain ``annotator``+;
- content WRITE (create/update/delete unit or relationship, task claim /
  status)                                                 — ``content:write`` AND domain ``expert``+;
- task ASSIGN (lead assigns, lead/admin cancels)           — ``content:write`` AND domain ``lead``.

A non-member is rejected fail-closed with 403 「无该域权限」 by
``require_domain_role`` before any handler runs; a domain that does not exist
is only reachable by an admin typo (admin bypasses the domain check) and gets
an honest 404. Content never leaves the caller's domain: every kernel call is
pinned to ``domain_key`` / ``domain.id`` from the path, so cross-tenant reads
have no path even for a member of two domains.

The data layer is ``src/bench/authoring.py`` (kernel: vocabulary enforcement,
KU upsert with namespace=domain.key, append-only events, tasks); this module
stays a thin web surface with no direct SQL. Route params are named
``domain_key`` on every route because ``require_domain_role`` reads exactly
that path param.

Every page here lives under the domain console's prefix — ``/d/{domain_key}/…``
— so the six console areas and the authoring pages they link to share one
namespace per domain. The pre-C5 ``/workbench/{domain_key}/…`` prefix survives
only as a 302 (:func:`workbench_legacy_redirect`), never as a second home.

Unit ``external_key`` values contain ``->`` and ``:`` (relationships derive
``{from_key}->{kind}:{to_key}``), so every URL carrying a key percent-encodes
it (``url_for`` in templates, :func:`_unit_path` / :func:`_path_key` here) and
decodes once on the way in.
"""

from __future__ import annotations

import json
from typing import Any, Optional
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from ..auth.deps import User, get_current_user, require_scope
from ..auth.domain_rbac import require_domain_role
from ..deps import DbConn, get_db
from ..templating import templates as _templates
from ...bench import authoring as bench_authoring
from ...bench import templates as bench_templates
from ...bench import workspaces

read_only_router = APIRouter(tags=["workbench"])
write_router = APIRouter(tags=["workbench"])

#: Ordered status ladder for display and for 「active first」 task sorting.
TASK_STATUSES = ("pending", "in_progress", "done", "cancelled")

# Two-gate composition per design D4 (platform scope ▶ domain role). Module
# constants so every route binds the same dependency instances.
_READ_GATES = [
    Depends(require_scope("content:read")),
    Depends(require_domain_role("annotator")),
]
_WRITE_GATES = [
    Depends(require_scope("content:write")),
    Depends(require_domain_role("expert")),
]
_ASSIGN_GATES = [
    Depends(require_scope("content:write")),
    Depends(require_domain_role("lead")),
]


def _flash(
    path: str, msg: str, err: bool = False, status: int = 303, **interp
) -> RedirectResponse:
    """Redirect with a flash message — same contract as ``admin.py::_flash``.

    ``msg`` is a dotted i18n key resolved by ``base.html``'s ``tr`` helper;
    ``**interp`` values ride along as extra query params (the base template
    forwards ``name`` and ``detail`` into ``tr``). A raw (non-key) message
    passes through.
    """
    sep = "&" if "?" in path else "?"
    q = f"msg={quote(msg)}"
    if err:
        q += "&err=1"
    for key, val in interp.items():
        q += f"&{key}={quote(str(val))}"
    return RedirectResponse(f"{path}{sep}{q}", status_code=status)


def _operator_of(user: User) -> str:
    """Stable, readable operator stamp — same construction as admin/review."""
    return user.email or user.name or user.sub


def _is_admin(user: User) -> bool:
    scopes = user.scopes or []
    return "*" in scopes or "admin" in scopes


def _get_domain_or_404(conn: DbConn, domain_key: str) -> dict:
    """Resolve the path domain or 404.

    ``require_domain_role`` already 403'd every non-member (fail-closed), so
    ``None`` here is only reachable for an admin (who bypasses the domain
    check) — return an honest 404 for the typo instead of leaking anything.
    """
    domain = workspaces.get_domain(conn, domain_key=domain_key)
    if domain is None:
        raise HTTPException(status_code=404, detail=f"domain {domain_key!r} not found")
    return domain


def _anchored_schema(conn: DbConn, domain: dict) -> dict:
    """The exact template-version schema the domain is anchored to."""
    tmpl = bench_templates.get_template_by_id(conn, template_id=domain["template_id"])
    return (tmpl or {}).get("schema") or {}


def _kind_lane(schema: dict, kind: str) -> Optional[str]:
    """``'entity'`` | ``'relationship'`` | ``None`` (kind outside the vocab).

    The browse/form routes 404 on ``None`` (spec: 出表 kind 浏览 404).
    """
    if kind in (schema.get("entity_types") or []):
        return "entity"
    if kind in (schema.get("relationship_kinds") or []):
        return "relationship"
    return None


def _capability(conn: DbConn, domain: dict, user: User) -> dict:
    """What the signed-in member may do here — for chrome only.

    The route gates stay authoritative; this only drives show/hide. ``role`` is
    the active workspace role, or ``'admin'`` for a platform admin arriving via
    the bypass (no membership row).
    """
    is_admin = _is_admin(user)
    role = workspaces.get_active_role(conn, domain_id=domain["id"], user_id=user.sub)
    if not role and is_admin:
        role = "admin"
    return {
        "role": role or "",
        "can_write": is_admin or role in ("expert", "lead"),
        "can_assign": is_admin or role == "lead",
    }


def _path_key(value: str) -> str:
    """Route-side decode of a percent-encoded path segment.

    ASGI servers (and the test client) already percent-decode ``scope["path"]``
    once before routing, so for keys like ``a->belongs_to:b`` this is a no-op;
    it only matters for a deployment that hands the route the still-encoded
    segment. Values without ``%`` pass through untouched.
    """
    return unquote(value) if "%" in value else value


def _unit_path(domain_key: str, kind: str, unit_key: str) -> str:
    """Percent-safe URL for one unit detail page (keys carry ``->`` and ``:``)."""
    return (
        f"/d/{quote(domain_key, safe='')}/units/"
        f"{quote(kind, safe='')}/{quote(unit_key, safe='')}"
    )


def _parse_tags(raw: str) -> tuple[Optional[dict], Optional[str]]:
    """Parse the tags textarea: comma-separated ``key=value`` pairs.

    The ONE documented convention (hinted in the form): ``k=v`` pairs split on
    commas, e.g. ``domain=law, status=draft``; whitespace around separators is
    stripped, values keep inner spaces. ``(None, problem)`` on a malformed
    chunk; ``({}, None)`` when empty.
    """
    text = (raw or "").strip()
    if not text:
        return {}, None
    tags: dict[str, str] = {}
    for chunk in text.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            return None, f"expected key=value, got {chunk!r}"
        key, _, value = chunk.partition("=")
        key = key.strip()
        if not key:
            return None, f"empty tag key in {chunk!r}"
        tags[key] = value.strip()
    return tags, None


def _editable_tags_text(unit: dict) -> str:
    """Serialize a unit's tags back into the form convention for editing.

    The internal soft-delete marker (``tags['deleted']``) is kernel-managed, so
    it is hidden from the editable text and re-merged server-side on save.
    """
    tags = dict(unit.get("tags") or {})
    tags.pop("deleted", None)
    return ", ".join(f"{k}={v}" for k, v in tags.items())


def _pretty(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, indent=2)


def sorted_tasks(tasks: list[dict]) -> list[dict]:
    """Active statuses first (pending ▶ in_progress), then newest id first.

    Shared with the domain console overview (`console_overview`), which is the
    single domain home since C5: the ordering rule must exist in exactly one
    place, so it lives here next to TASK_STATUSES.
    """
    order = {status: rank for rank, status in enumerate(TASK_STATUSES)}
    return sorted(
        tasks,
        key=lambda task: (
            order.get(str(task.get("status")), len(order)),
            -int(task.get("id") or 0),
        ),
    )


# ------------------------------------------------------- legacy /workbench #
#
# C5 moved the authoring surface under the domain console (`/d/{domain_key}/…`)
# so a domain has ONE URL namespace: the console areas and the authoring pages
# it links to now share a prefix. These two routes keep every old
# `/workbench/{key}/…` link, bookmark and machine-side deep link working.
#
# They carry the same read gates as the pages they replace, so a non-member is
# still rejected with 403 BEFORE any redirect rather than being bounced to a
# page that then denies. Only GET is redirected: every in-app form is rendered
# by our own templates through `url_for`, so it posts to the new path, and a
# stale POST would be a replay of an old form — 405 is the honest answer.


@read_only_router.get(
    "/workbench/{domain_key}", include_in_schema=False,
    name="workbench_legacy_home", dependencies=_READ_GATES,
)
@read_only_router.get(
    "/workbench/{domain_key}/{rest:path}", include_in_schema=False,
    name="workbench_legacy_path", dependencies=_READ_GATES,
)
def workbench_legacy_redirect(
    request: Request, domain_key: str, rest: str = ""
) -> RedirectResponse:
    """302 an old ``/workbench/…`` URL onto its ``/d/…`` home.

    ``rest`` arrives percent-decoded, so each segment is re-encoded on the way
    out — unit keys carry ``->`` and ``:`` and must survive the hop intact.
    The query string (filters, ``limit``) is carried over verbatim.
    """
    target = f"/d/{quote(domain_key, safe='')}"
    if rest:
        target += "/" + "/".join(quote(part, safe="") for part in rest.split("/"))
    if request.url.query:
        target += f"?{request.url.query}"
    return RedirectResponse(target, status_code=302)


# ---------------------------------------------------------------- browse #


@read_only_router.get(
    "/d/{domain_key}/browse/{kind}", include_in_schema=False,
    name="workbench_browse", dependencies=_READ_GATES,
)
def workbench_browse(
    request: Request,
    domain_key: str,
    kind: str,
    limit: int = Query(50, ge=1, le=200),
    # The route fetches `offset + limit + 1` rows in one go (the extra row is the
    # has-next signal), so `offset` bounds the memory this endpoint can be made
    # to allocate. Without a ceiling, `?offset=50000000` asked Postgres for fifty
    # million rows and ``fetchall()`` materialised them — any domain member with
    # content:read could OOM the workbench pod by editing a URL.
    offset: int = Query(0, ge=0, le=10000),
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Paginated unit list for one in-vocabulary kind (out-of-table 404s)."""
    domain = _get_domain_or_404(db, domain_key)
    schema = _anchored_schema(db, domain)
    lane = _kind_lane(schema, kind)
    if lane is None:
        raise HTTPException(
            status_code=404, detail=f"kind {kind!r} is not in this domain's template"
        )
    # One fetch overlapping the page window: slicing pages it client-side and
    # the extra row is the has-next signal (the kernel list API has no offset).
    fetched = bench_authoring.authoring_list_units(
        db, domain_key=domain_key, kind=kind, limit=offset + limit + 1
    )
    rows = fetched[offset : offset + limit]
    return _templates.TemplateResponse(
        request,
        "workbench_browse.html",
        {
            "domain": domain,
            "kind": kind,
            "lane": lane,
            "rows": rows,
            "limit": limit,
            "offset": offset,
            "has_next": len(fetched) > offset + limit,
            "has_prev": offset > 0,
            "cap": _capability(db, domain, user),
        },
    )


# ----------------------------------------------------------------- units #


@read_only_router.get(
    "/d/{domain_key}/units/{kind}/new", include_in_schema=False,
    name="workbench_unit_new", dependencies=_WRITE_GATES,
)
def workbench_unit_new_form(
    request: Request,
    domain_key: str,
    kind: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create form (write-gated: the form is part of the write flow)."""
    domain = _get_domain_or_404(db, domain_key)
    schema = _anchored_schema(db, domain)
    lane = _kind_lane(schema, kind)
    if lane is None:
        raise HTTPException(
            status_code=404, detail=f"kind {kind!r} is not in this domain's template"
        )
    return _templates.TemplateResponse(
        request,
        "workbench_unit_form.html",
        {
            "domain": domain,
            "kind": kind,
            "lane": lane,
            "mode": "create",
            "form_action": None,  # computed in-template via url_for
            "body_value": "",
            "tags_text": "",
            "external_key_value": "",
            "from_value": "",
            "to_value": "",
            "rel_key_template": bench_authoring.RELATIONSHIP_KEY_TEMPLATE,
            "cap": _capability(db, domain, user),
        },
    )


@write_router.post(
    "/d/{domain_key}/units/{kind}/new", include_in_schema=False,
    name="workbench_unit_create", dependencies=_WRITE_GATES,
)
async def workbench_unit_create(
    request: Request,
    domain_key: str,
    kind: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("content:write")),
):
    """Create one entity or relationship through the kernel authoring entry."""
    domain = _get_domain_or_404(db, domain_key)
    schema = _anchored_schema(db, domain)
    lane = _kind_lane(schema, kind)
    if lane is None:
        raise HTTPException(
            status_code=404, detail=f"kind {kind!r} is not in this domain's template"
        )
    form = await request.form()
    body = str(form.get("body") or "").strip()
    back = f"/d/{quote(domain_key, safe='')}/units/{quote(kind, safe='')}/new"
    if not body:
        return _flash(back, "flash.unit_body_required", err=True)
    tags, problem = _parse_tags(str(form.get("tags") or ""))
    if problem is not None:
        return _flash(back, "flash.unit_failed", err=True, detail=problem)
    try:
        if lane == "relationship":
            from_key = str(form.get("from_key") or "").strip()
            to_key = str(form.get("to_key") or "").strip()
            if not from_key or not to_key:
                raise ValueError("from_key and to_key are required")
            unit = bench_authoring.authoring_create_relationship(
                db, domain_key=domain_key, kind=kind,
                from_key=from_key, to_key=to_key,
                body=body, operator=_operator_of(user),
            )
        else:
            external_key = str(form.get("external_key") or "").strip()
            if not external_key:
                raise ValueError("external_key is required")
            unit = bench_authoring.authoring_create_unit(
                db, domain_key=domain_key, kind=kind, external_key=external_key,
                body=body, operator=_operator_of(user), tags=tags,
            )
    except ValueError as exc:
        # Kernel messages name the vocabulary / domain problem — surface as-is.
        return _flash(back, "flash.unit_failed", err=True, detail=str(exc))
    return _flash(_unit_path(domain_key, kind, unit["external_key"]), "flash.unit_created")


@read_only_router.get(
    "/d/{domain_key}/units/{kind}/{unit_key}", include_in_schema=False,
    name="workbench_unit_detail", dependencies=_READ_GATES,
)
def workbench_unit_detail(
    request: Request,
    domain_key: str,
    kind: str,
    unit_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """All unit fields + this unit's append-only event history + edit/delete."""
    domain = _get_domain_or_404(db, domain_key)
    schema = _anchored_schema(db, domain)
    lane = _kind_lane(schema, kind)
    if lane is None:
        raise HTTPException(
            status_code=404, detail=f"kind {kind!r} is not in this domain's template"
        )
    unit = bench_authoring.authoring_get_unit(
        db, domain_key=domain_key, kind=kind, external_key=_path_key(unit_key)
    )
    if unit is None:
        raise HTTPException(status_code=404, detail="unit not found")
    deleted = bool((unit.get("tags") or {}).get("deleted"))
    events = bench_authoring.authoring_events_for(
        db, domain_id=domain["id"], unit_kind=kind,
        unit_key=unit["external_key"], limit=50,
    )
    return _templates.TemplateResponse(
        request,
        "workbench_unit_detail.html",
        {
            "domain": domain,
            "kind": kind,
            "lane": lane,
            "unit": unit,
            "deleted": deleted,
            "events": events,
            "attrs_json": _pretty(unit.get("attrs")),
            "provenance_json": _pretty(unit.get("provenance")),
            "tags_text": _editable_tags_text(unit),
            "cap": _capability(db, domain, user),
        },
    )


@write_router.post(
    "/d/{domain_key}/units/{kind}/{unit_key}/edit", include_in_schema=False,
    name="workbench_unit_edit", dependencies=_WRITE_GATES,
)
async def workbench_unit_edit(
    request: Request,
    domain_key: str,
    kind: str,
    unit_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("content:write")),
):
    """Update body/tags through the kernel; the identity key never moves."""
    domain = _get_domain_or_404(db, domain_key)
    schema = _anchored_schema(db, domain)
    if _kind_lane(schema, kind) is None:
        raise HTTPException(
            status_code=404, detail=f"kind {kind!r} is not in this domain's template"
        )
    external_key = _path_key(unit_key)
    back = _unit_path(domain_key, kind, external_key)
    unit = bench_authoring.authoring_get_unit(
        db, domain_key=domain_key, kind=kind, external_key=external_key
    )
    if unit is None:
        raise HTTPException(status_code=404, detail="unit not found")
    form = await request.form()
    body = str(form.get("body") or "").strip()
    if not body:
        return _flash(back, "flash.unit_body_required", err=True)
    tags, problem = _parse_tags(str(form.get("tags") or ""))
    if problem is not None:
        return _flash(back, "flash.unit_failed", err=True, detail=problem)
    # Preserve the kernel-managed soft-delete marker across edits so updating a
    # deleted row cannot resurrect it (the upsert replaces tags wholesale).
    merged = dict(tags or {})
    if (unit.get("tags") or {}).get("deleted"):
        merged["deleted"] = True
    try:
        bench_authoring.authoring_update_unit(
            db, domain_key=domain_key, kind=kind, external_key=external_key,
            body=body, operator=_operator_of(user), tags=merged,
        )
    except ValueError as exc:
        return _flash(back, "flash.unit_failed", err=True, detail=str(exc))
    return _flash(back, "flash.unit_updated")


@write_router.post(
    "/d/{domain_key}/units/{kind}/{unit_key}/delete",
    include_in_schema=False, name="workbench_unit_delete", dependencies=_WRITE_GATES,
)
async def workbench_unit_delete(
    request: Request,
    domain_key: str,
    kind: str,
    unit_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("content:write")),
):
    """Soft delete: the kernel tags ``deleted=true`` and records the event."""
    domain = _get_domain_or_404(db, domain_key)
    schema = _anchored_schema(db, domain)
    if _kind_lane(schema, kind) is None:
        raise HTTPException(
            status_code=404, detail=f"kind {kind!r} is not in this domain's template"
        )
    external_key = _path_key(unit_key)
    back = _unit_path(domain_key, kind, external_key)
    try:
        bench_authoring.authoring_delete_unit(
            db, domain_key=domain_key, kind=kind, external_key=external_key,
            operator=_operator_of(user),
        )
    except ValueError as exc:
        return _flash(back, "flash.unit_failed", err=True, detail=str(exc))
    return _flash(
        f"/d/{quote(domain_key, safe='')}/browse/{quote(kind, safe='')}",
        "flash.unit_deleted",
    )


# ----------------------------------------------------------------- tasks #


@read_only_router.get(
    "/d/{domain_key}/tasks/new", include_in_schema=False,
    name="workbench_task_new", dependencies=_ASSIGN_GATES,
)
def workbench_task_new_form(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Lead-only assignment form: pick a member and an in-vocabulary target."""
    domain = _get_domain_or_404(db, domain_key)
    schema = _anchored_schema(db, domain)
    members = workspaces.list_members(db, domain_id=domain["id"])
    return _templates.TemplateResponse(
        request,
        "workbench_task_form.html",
        {
            "domain": domain,
            "members": members,
            "entity_types": list(schema.get("entity_types") or []),
            "relationship_kinds": list(schema.get("relationship_kinds") or []),
            "cap": _capability(db, domain, user),
        },
    )


@write_router.post(
    "/d/{domain_key}/tasks/new", include_in_schema=False,
    name="workbench_task_create", dependencies=_ASSIGN_GATES,
)
async def workbench_task_create(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("content:write")),
):
    """Assign a creation/verification task to a domain member (lead-only)."""
    domain = _get_domain_or_404(db, domain_key)
    schema = _anchored_schema(db, domain)
    back = f"/d/{quote(domain_key, safe='')}/tasks/new"
    form = await request.form()
    assignee = str(form.get("assignee") or "").strip()
    title = str(form.get("title") or "").strip()
    detail = str(form.get("detail") or "").strip() or None
    target_kind = str(form.get("target_kind") or "").strip() or None
    target_key = str(form.get("target_key") or "").strip() or None
    if not assignee:
        return _flash(back, "flash.task_failed", err=True, detail="assignee is required")
    if not title:
        return _flash(back, "flash.task_failed", err=True, detail="title is required")
    if target_kind is not None and _kind_lane(schema, target_kind) is None:
        raise HTTPException(
            status_code=404,
            detail=f"kind {target_kind!r} is not in this domain's template",
        )
    try:
        bench_authoring.authoring_create_task(
            db, domain_id=domain["id"], assignee=assignee, title=title,
            detail=detail, target_kind=target_kind, target_key=target_key,
            created_by=_operator_of(user),
        )
    except ValueError as exc:
        return _flash(back, "flash.task_failed", err=True, detail=str(exc))
    return _flash(
        f"/d/{quote(domain_key, safe='')}",
        "flash.task_assigned", name=assignee,
    )


@write_router.post(
    "/d/{domain_key}/tasks/{task_id}/status", include_in_schema=False,
    name="workbench_task_status", dependencies=_WRITE_GATES,
)
async def workbench_task_status(
    request: Request,
    domain_key: str,
    task_id: int,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("content:write")),
):
    """Claim / complete / cancel one task.

    Expert+ gate (route deps) plus in-handler ownership rules per design D4:
    claim/complete belong to the assignee only; cancelling is lead/admin only.
    The task must live in THIS domain — a foreign-domain task_id 404s rather
    than leaking that it exists.
    """
    domain = _get_domain_or_404(db, domain_key)
    back = f"/d/{quote(domain_key, safe='')}"
    task = bench_authoring.authoring_get_task(db, task_id=task_id)
    if task is None or task.get("domain_id") != domain["id"]:
        raise HTTPException(status_code=404, detail="task not found")
    form = await request.form()
    to_status = str(form.get("to_status") or "").strip()
    if to_status not in TASK_STATUSES:
        return _flash(
            back, "flash.task_failed", err=True,
            detail=f"to_status must be one of {list(TASK_STATUSES)}",
        )
    is_admin = _is_admin(user)
    role = workspaces.get_active_role(conn=db, domain_id=domain["id"], user_id=user.sub)
    if to_status == "cancelled":
        if not (is_admin or role == "lead"):
            return _flash(
                back, "flash.task_failed", err=True,
                detail="cancelling a task requires the lead role",
            )
    elif not (is_admin or task.get("assignee") == user.sub):
        return _flash(
            back, "flash.task_failed", err=True,
            detail="only the assignee can transition this task",
        )
    try:
        bench_authoring.authoring_transition_task(
            db, task_id=task_id, to_status=to_status, actor=user.sub
        )
    except ValueError as exc:
        return _flash(back, "flash.task_failed", err=True, detail=str(exc))
    return _flash(back, "flash.task_status_updated")


router = APIRouter(tags=["workbench"])
router.include_router(read_only_router)
router.include_router(write_router)
