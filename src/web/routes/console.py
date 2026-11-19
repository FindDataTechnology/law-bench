"""Domain-first console: the platform's front door and per-domain areas (C5).

Change ``add-domain-first-workbench``. This module is the human face of the
domain kernel built by C1–C4; it adds no ontology semantics of its own:

- ``/d`` — **my domains**. The authenticated landing point: one row per active
  membership, my own recency first. Replaces the old ``/`` → ``/rubrics``
  redirect, which dropped everyone into the legal rubric list regardless of
  which domain they actually work in.
- ``/d/{domain_key}`` — **overview**: four real counts (units, latest release,
  pending proposals, my tasks), the task panel (claim/complete/cancel still post
  to the existing workbench routes), the anchored vocabulary, recent changes.
- ``/d/{domain_key}/ontology`` — the four-layer ledger (declaration, curation,
  publication, consumption) plus the declaration-vs-corpus reconciliation. Pure
  read: the page is a projection of ``src.bench.ledger`` and never computes a
  digest of its own, so it can never disagree with the machine pull surface.
- ``/d/{domain_key}/inbox`` — the proposal inbox: drafts land here, a lead
  confirms them through the kernel's single write path, and rejections return
  the draft without auto-retry.
- ``/d/{domain_key}/publish`` — release history, consumers, pull footprints.
- ``/d/{domain_key}/bench`` — the domain's evaluation-asset shelf (a directory;
  it never changes an asset).
- ``/d/{domain_key}/settings`` — this domain's members and invitations.

Authorization is deliberately the same composition as ``authoring.py``: platform
scope first (Logto only), then the domain role (``domain_members`` only), then
the area's own minimum role. Every route names its path param ``domain_key``
because ``require_domain_role`` reads exactly that param. Navigation hiding is
usability; these dependencies are the enforcement.
"""

from __future__ import annotations

import json

from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..auth.deps import User, get_current_user, require_scope
from ..auth.domain_rbac import require_domain_role
from ..deps import DbConn, get_db
from ..domain_context import (
    capability,
    console_context,
    is_platform_admin,
    resolve_domain,
)
from ..templating import templates as _templates
from .authoring import sorted_tasks
from ...bench import authoring as bench_authoring
from ...bench import distribution as bench_distribution
from ...bench import domain_assets as bench_domain_assets
# Importing the legal pack registers its asset kinds with the kernel catalog.
# The kernel stays domain-free; this app IS the legal deployment, so the pack
# import belongs at the app's edge (this module), never inside src/bench.
from packs.legal import asset_catalog as _legal_asset_catalog  # noqa: F401
# Same rule for the second line: importing the gov pack registers its key-fold
# rules, so a gov title folds the same way in the catalog, the ontology and
# extraction. The pack itself stays outside src/bench.
from packs import gov as _gov_pack  # noqa: F401
from ...bench import ledger as bench_ledger
from ...bench import domain_rubrics
from ...bench import dispatch
from ...bench import estate
from ...bench import templates
from ...bench import libraries as library_store
from ...bench import proposals as bench_proposals
from ...bench import submitters as bench_submitters
from ...search import library_index
from ...bench import templates as bench_templates
from ...bench import workspaces

read_only_router = APIRouter(tags=["console"])
write_router = APIRouter(tags=["console"])

# Two-gate composition (platform scope ▶ domain role). ``viewer`` does not
# exist in the kernel's role vocabulary — the read floor is ``annotator``
# (审核标注员), which is read-only in the authoring surface too.
_READ_GATES = [
    Depends(require_scope("content:read")),
    Depends(require_domain_role("annotator")),
]
_WRITE_GATES = [
    Depends(require_scope("content:write")),
    Depends(require_domain_role("expert")),
]
_LEAD_GATES = [
    Depends(require_scope("content:write")),
    Depends(require_domain_role("lead")),
]


def _flash(
    path: str, msg: str, err: bool = False, status: int = 303, **interp
) -> RedirectResponse:
    """Redirect with a flash message — same contract as ``admin.py::_flash``."""
    sep = "&" if "?" in path else "?"
    q = f"msg={quote(msg)}"
    if err:
        q += "&err=1"
    for key, val in interp.items():
        q += f"&{key}={quote(str(val))}"
    return RedirectResponse(f"{path}{sep}{q}", status_code=status)


def _operator_of(user: User) -> str:
    return user.email or user.name or user.sub


def _anchored_schema(conn: DbConn, domain: dict) -> dict:
    """The exact template-version schema the domain is anchored to."""
    tmpl = bench_templates.get_template_by_id(conn, template_id=domain["template_id"])
    return (tmpl or {}).get("schema") or {}


# ------------------------------------------------------------------ landing #


@read_only_router.get(
    "/d", include_in_schema=False, name="console_domain_list",
    dependencies=[Depends(require_scope("content:read"))],
)
def console_domain_list(
    request: Request,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """My domains — the authenticated landing point.

    A platform admin with no membership sees the empty state plus the platform
    gate: the page never invents a domain, and never lists a domain the caller
    cannot enter.
    """
    include_archived = (request.query_params.get("archived") or "") == "1"
    domains = workspaces.list_member_domains(db, user_id=user.sub)
    if include_archived and is_platform_admin(user):
        # The archive view is an admin's roll-call of retired lines; it is not a
        # place to work, so it lists every domain regardless of membership.
        domains = [
            {**d, "role": "admin", "last_opened_at": None}
            for d in workspaces.list_domains(db, include_archived=True)
        ]
    elif not domains and is_platform_admin(user):
        # A platform admin's visible range is every domain, not just the ones
        # they hold a membership in: otherwise the estate console (the page that
        # answers "what is missing where") is empty for the only role that can
        # act on it. Role is reported as 'admin' — an honest label for a bypass,
        # not a fabricated membership row.
        domains = [
            {**d, "role": "admin", "last_opened_at": None}
            for d in workspaces.list_domains(db)
        ]
    # Estate view (add-domain-tree-and-shared-libraries §4.2): the landing page
    # used to be "the domains I belong to". With many sub-domains the operator's
    # real question is "what is missing where", so every row carries its four
    # pillar summaries and its gaps.
    gap = (request.query_params.get("gap") or "").strip() or None
    # One matrix, two views of it. The gap chips used to re-run the whole matrix
    # (a second external count per domain; /d measured 1465ms warm), which is
    # also a second chance for the chips and the rows to disagree.
    all_rows = estate.matrix(db, domains=domains)
    rows = estate.filter_rows(all_rows, gap)
    return _templates.TemplateResponse(
        request,
        "domain_list.html",
        {
            "domains": domains,
            "rows": rows,
            "gap": gap,
            "include_archived": include_archived,
            "pillars": estate.PILLARS,
            "gap_counts": {
                key: len([r for r in all_rows if key in r["gaps"]])
                for key in ("ontology", "knowledge", "eval")
            },
            "platform_admin": is_platform_admin(user),
        },
    )


@write_router.post(
    "/d/{domain_key}/eval-runs/lane-probe", include_in_schema=False,
    name="console_lane_probe",
    dependencies=[Depends(require_scope("content:write"))],
)
async def console_lane_probe(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Ask the model lane one question and show its own answer.

    Deliberately a POST and deliberately manual: probing on page load would
    hammer a dead endpoint and turn every view into a latency trap. The result
    is passed back as a short query param so it is shown once and not stored —
    a cached "last known good" would become the next lie.
    """
    from ...bench import lane as bench_lane

    domain = resolve_domain(db, domain_key)
    require_domain_role("lead")(request, user=user, conn=db)
    result = bench_lane.probe()
    summary = "ok" if result["ok"] else f"{result['status'] or 'err'}: {result['detail'][:160]}"
    return _flash(
        f"/d/{quote(domain_key)}/eval-runs", "flash.lane_probe", err=not result["ok"],
        detail=summary,
    )


@write_router.post(
    "/d/{domain_key}/inbox/batch", include_in_schema=False,
    name="console_proposal_batch",
    dependencies=[Depends(require_scope("content:write"))],
)
async def console_proposal_batch(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Confirm or reject a whole extraction batch, row by row.

    Each proposal goes through the same confirm/reject path a single one does, so
    the kernel still writes and still trails. One failing row does **not** roll
    back the others: partial success is reported as such.
    """
    domain = resolve_domain(db, domain_key)
    require_domain_role("lead")(request, user=user, conn=db)
    form = await request.form()
    batch = (form.get("batch") or "").strip()
    action = (form.get("action") or "").strip()
    if action not in ("confirm", "reject"):
        raise HTTPException(status_code=422, detail="action must be confirm or reject")
    rows = bench_proposals.list_proposals(db, domain_key=domain_key, state="pending",
                                          batch=batch or None)
    ok = failed = 0
    for row in rows:
        try:
            actor = user.email or user.name or user.sub
            if action == "confirm":
                # The kernel's own signature: `actor` decides attribution and
                # whether the caller was a platform admin driving an override.
                bench_proposals.confirm(
                    db, domain_key=domain_key, proposal_id=row["id"], actor=actor,
                    admin_override=is_platform_admin(user),
                )
            else:
                bench_proposals.reject(
                    db, domain_key=domain_key, proposal_id=row["id"],
                    actor=actor, note="batch reject",
                )
            ok += 1
        except ValueError:
            failed += 1
    return _flash(
        f"/d/{quote(domain_key)}/inbox" + (f"?batch={quote(batch)}" if batch else ""),
        "flash.proposal_batch_done", ok=ok, failed=failed,
    )


@write_router.post(
    "/d/{domain_key}/inbox/tasks/{task_id}/transition", include_in_schema=False,
    name="console_task_transition",
    dependencies=[Depends(require_scope("content:write"))],
)
async def console_task_transition(
    request: Request,
    domain_key: str,
    task_id: int,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Close (or start) a dispatched task — assignee or domain lead.

    Without this the batch dispatch is one-way: the task stays open, and the
    idempotency rule ("already assigned") then blocks ever dispatching that gap
    again. Closing is what makes the loop re-runnable.
    """
    domain = resolve_domain(db, domain_key)
    task = bench_authoring.authoring_get_task(db, task_id=task_id)
    if task is None or task["domain_id"] != domain["id"]:
        raise HTTPException(status_code=404, detail="task not found in this domain")
    form = await request.form()
    to_status = (form.get("to") or "").strip()
    actor = user.email or user.name or user.sub
    role = workspaces.get_active_role(db, domain_id=domain["id"], user_id=user.sub)
    # Authorization reads the type first: a human order is personal (its display
    # name IS the identity reference), while kernel-role/fleet orders belong to
    # an execution side no logged-in person *is* — only a lead/admin moves those,
    # so a human whose name coincides with a fleet label cannot inherit it.
    kind = task.get("assignee_kind") or "human"
    mine = (
        task["assignee"] in {user.sub, user.email, user.name}
        if kind == "human"
        else False
    )
    if not (mine or role == "lead" or is_platform_admin(user)):
        raise HTTPException(status_code=403, detail="only the assignee or a domain lead may update this task")
    try:
        # Claim and completion are their own transitions (exclusive claim,
        # no pending→done shortcut); everything else keeps the old path.
        if to_status == "in_progress":
            bench_authoring.authoring_claim_task(db, task_id=task_id, actor=actor)
        elif to_status == "done":
            bench_authoring.authoring_complete_task(
                db, task_id=task_id, actor=actor,
                note=(form.get("note") or "").strip() or None,
            )
        else:
            bench_authoring.authoring_transition_task(
                db, task_id=task_id, to_status=to_status, actor=actor,
            )
    except bench_authoring.TaskAlreadyClaimed as exc:
        return _flash(f"/d/{quote(domain_key)}/inbox", "flash.task_already_claimed",
                      err=True, detail=str(exc))
    except ValueError as exc:
        return _flash(f"/d/{quote(domain_key)}/inbox", "flash.task_transition_failed",
                      err=True, detail=str(exc))
    return _flash(f"/d/{quote(domain_key)}/inbox", "flash.task_transitioned")


@write_router.post(
    "/d/{domain_key}/knowledge/narrow", include_in_schema=False,
    name="console_knowledge_narrow",
    dependencies=[Depends(require_scope("content:write"))],
)
async def console_knowledge_narrow(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Let a domain lead narrow its own corpus scope (subtraction only).

    A sub-domain owner knows what *their* slice needs; asking a platform admin to
    edit it is the friction this page removes. The write is validated against the
    parent's effective set at submit time (``libraries.narrow``), so an attempt to
    widen fails here with a specific message instead of leaving a broken scope for
    the next page load to trip over. Expanding back happens the same way — pick
    more sources, up to whatever the parent granted.
    """
    from ..auth.domain_rbac import require_domain_role

    domain = resolve_domain(db, domain_key)
    require_domain_role("lead")(request, user=user, conn=db)
    form = await request.form()
    library_key = (form.get("library_key") or "").strip()
    picked = [s for s in form.getlist("source") if s]
    try:
        library_store.narrow(
            db,
            domain_id=domain["id"],
            domain_path=domain["path"],
            library_key=library_key,
            sources=picked,
            created_by=user.email or user.name or user.sub,
        )
    except ValueError as exc:
        return _flash(
            f"/d/{quote(domain_key)}/knowledge", "flash.narrow_failed", err=True,
            detail=str(exc),
        )
    return _flash(
        f"/d/{quote(domain_key)}/knowledge", "flash.narrowed", n=len(picked)
    )


@write_router.post(
    "/d/{domain_key}/archive", include_in_schema=False, name="console_domain_archive",
    dependencies=[Depends(require_scope("admin"))],
)
async def console_domain_archive(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Retire a domain: it leaves the estate, everything it holds stays.

    Admin-only on purpose. A domain lead retiring their own line would remove it
    from the operator's roll-call while the platform still believed it healthy.
    """
    form = await request.form()
    restore = (form.get("restore") or "") == "1"
    try:
        if restore:
            workspaces.restore_domain(db, domain_key=domain_key, actor=user.sub)
        else:
            workspaces.archive_domain(db, domain_key=domain_key, actor=user.sub)
    except ValueError as exc:
        return _flash("/d?archived=1", "flash.domain_archive_failed", err=True, detail=str(exc))
    return _flash(
        "/d" if not restore else "/d?archived=1",
        "flash.domain_restored" if restore else "flash.domain_archived",
        key=domain_key,
    )


# ------------------------------------------------------------- dispatch #


def _estate_domains(db, user, *, include_archived: bool = False) -> list[dict]:
    """The domains this caller can see on the estate page — one definition.

    Shared by the matrix and the dispatch planner so a task can never be created
    for a domain the caller could not see in the first place. ``include_archived``
    is the admin's roll-call of retired lines; dispatch never uses it (you do not
    hand out work on a domain that has left the estate).
    """
    domains = workspaces.list_member_domains(db, user_id=user.sub)
    if include_archived and is_platform_admin(user):
        domains = [
            {**d, "role": "admin", "last_opened_at": None}
            for d in workspaces.list_domains(db, include_archived=True)
        ]
    elif not domains and is_platform_admin(user):
        domains = [
            {**d, "role": "admin", "last_opened_at": None}
            for d in workspaces.list_domains(db)
        ]
    return domains


@read_only_router.get(
    "/d/dispatch", include_in_schema=False, name="console_dispatch_preview",
    dependencies=[Depends(require_scope("content:read"))],
)
def console_dispatch_preview(
    request: Request,
    gap: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Confirmation step — **read-only**, by design.

    A batch that created tasks while rendering a filtered list would be one
    refresh away from duplicates, so the plan is shown here and written only on
    the POST below.
    """
    domains = _estate_domains(db, user)
    try:
        rows = dispatch.rows_for_gap(db, domains=domains, gap=gap)
        plan = dispatch.plan(db, rows=rows, gap=gap, assignee="")
    except ValueError as exc:
        return _flash("/d", str(exc), err=True)

    route = dispatch.route_for(gap)
    kernel_role = dispatch.kernel_role_for(gap)
    # 舰队下拉只列「绑定了本次将派到的域」的活登记：列一支绑在别的域的舰队，
    # 是给操作者一个点了必然失败的选项。
    target_keys = {d["key"] for d in plan["will_create"] + plan["already_open"]}
    fleets = [
        c
        for c in bench_distribution.list_consumers(db)
        if (c.get("kind") or "machine") == "fleet"
        and c.get("revoked_at") is None
        and target_keys & set(c.get("domains") or [])
    ]
    return _templates.TemplateResponse(
        request,
        "domain_dispatch.html",
        {
            "plan": plan,
            "platform_admin": is_platform_admin(user),
            "route": route,
            "kernel_role": kernel_role,
            "human_only": route == dispatch.HUMAN_ROUTE,
            "fleets": fleets,
        },
    )


@write_router.post(
    "/d/dispatch", include_in_schema=False, name="console_dispatch_confirm",
    dependencies=[Depends(require_scope("content:write"))],
)
async def console_dispatch_confirm(
    request: Request,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create one task per domain still missing the gap (idempotent per pillar).

    The assignee is typed now: ``assignee_kind`` picks which of the three kinds
    it is, and the reference is what authorization reads. Dispatch never decides
    *who* on its own — it records the operator's choice and refuses choices the
    route table contradicts (a kernel-owned gap cannot be handed to someone the
    table never assigned it to).
    """
    form = await request.form()
    gap = (form.get("gap") or "").strip()
    assignee = (form.get("assignee") or "").strip()
    assignee_kind = (form.get("assignee_kind") or "human").strip()
    assignee_ref = (form.get("assignee_ref") or "").strip() or None
    domains = _estate_domains(db, user)
    try:
        rows = dispatch.rows_for_gap(db, domains=domains, gap=gap)
        result = dispatch.dispatch(
            db, rows=rows, gap=gap, assignee=assignee,
            created_by=user.email or user.name or user.sub,
            assignee_kind=assignee_kind,
            assignee_ref=assignee_ref,
        )
    except ValueError as exc:
        return _flash("/d", str(exc), err=True)
    return _flash(
        f"/d?gap={quote(gap)}",
        "flash.dispatch_done",
        n=len(result["created"]),
        skipped=len(result["already_open"]),
    )


@read_only_router.get(
    "/d/switch", include_in_schema=False, name="console_switch",
    dependencies=[Depends(require_scope("content:read"))],
)
def console_switch(
    to: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Server-validated domain switch (the switcher's GET target).

    The form value is a *candidate*: membership is re-checked here, so a
    hand-edited value cannot reach a domain the caller is not a member of. A
    platform admin may switch anywhere (the same bypass the route gates use).
    """
    target = workspaces.get_domain(db, domain_key=to)
    if target is None:
        raise HTTPException(status_code=404, detail=f"domain {to!r} not found")
    if not is_platform_admin(user):
        role = workspaces.get_active_role(
            db, domain_id=target["id"], user_id=user.sub
        )
        if role is None:
            raise HTTPException(status_code=403, detail="无该域权限")
    return RedirectResponse(
        f"/d/{quote(target['key'], safe='')}", status_code=303
    )


# ----------------------------------------------------------------- overview #


# ------------------------------------------------------------ new domain #


@read_only_router.get(
    "/d/new", include_in_schema=False, name="console_new_domain",
    dependencies=[Depends(require_scope("admin"))],
)
def console_new_domain(
    request: Request,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The sub-domain wizard: pick a parent, preview inheritance, then create.

    Creating a domain is an **admin** action (the same gate as ``/admin``): the
    wizard exists to make it a five-minute job, not to widen who may do it.
    """
    parents = workspaces.list_domains(db)
    parent_key = (request.query_params.get("parent") or "").strip() or None
    preview = None
    if parent_key:
        parent = workspaces.get_domain(db, domain_key=parent_key)
        if parent is not None:
            parent_template = templates.get_template_by_id(
                db, template_id=parent["template_id"]
            )
            try:
                scope = library_index.explain_scope(db, domain_path=parent["path"])
            except ValueError as exc:
                scope = {"libraries": [], "error": str(exc)}
            preview = {
                "parent": parent,
                "template": parent_template,
                "scope": scope,
            }
    return _templates.TemplateResponse(
        request,
        "domain_new.html",
        {
            "parents": parents,
            "parent_key": parent_key,
            "preview": preview,
            "libraries": library_store.list_libraries(db),
        },
    )


@write_router.post(
    "/d/new", include_in_schema=False, name="console_new_domain_create",
    dependencies=[Depends(require_scope("admin"))],
)
async def console_new_domain_create(
    request: Request,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create the sub-domain, subscribe it to the chosen sources, land on it.

    Subscriptions are applied **after** creation and are narrowed against the
    parent: a wizard selection that would widen the parent's scope is refused by
    ``effective_sources`` and rolled back, so the wizard cannot produce a domain
    whose scope the retriever would then reject.
    """
    form = await request.form()
    key = (form.get("key") or "").strip()
    name = (form.get("name") or "").strip()
    parent_key = (form.get("parent_key") or "").strip() or None
    selected = form.getlist("source")  # "library_key:source_key"
    try:
        created = workspaces.instantiate_domain(
            db,
            key=key,
            name=name,
            template_name=(form.get("template_name") or "").strip(),
            template_version=(
                int(form.get("template_version"))
                if (form.get("template_version") or "").strip()
                else None
            ),
            created_by=_operator_of(user),
            parent_key=parent_key,
        )
        if selected:
            by_lib: dict[str, list[str]] = {}
            for token in selected:
                lib, _, src = token.partition(":")
                if lib and src:
                    by_lib.setdefault(lib, []).append(src)
            for lib_key, sources in by_lib.items():
                library_store.subscribe(
                    db,
                    domain_id=created["id"],
                    library_key=lib_key,
                    created_by=_operator_of(user),
                    source_filter=sources,
                )
            # Prove the result is a legal scope before declaring success: this is
            # the same resolver retrieval uses, so a bad selection fails here.
            library_index.explain_scope(db, domain_path=created["path"])
    except ValueError as exc:
        db.rollback()
        return _flash(
            f"/d/new?parent={quote(parent_key or '', safe='')}",
            "console.flash.domain_create_failed",
            err=True,
            detail=str(exc),
        )
    return _flash(
        f"/d/{quote(created['key'], safe='')}", "console.flash.domain_created",
        name=created["name"],
    )


@read_only_router.get(
    "/d/{domain_key}", include_in_schema=False, name="console_overview",
    dependencies=_READ_GATES,
)
def console_overview(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Domain overview: four real counts, my tasks, who is running, recent changes."""
    from ...bench import agent_runs

    domain = resolve_domain(db, domain_key)
    schema = _anchored_schema(db, domain)
    ctx = console_context(db, domain, user, touch=True)
    curation = bench_ledger.curation_layer(db, domain=domain, recent_limit=5)
    publication = bench_ledger.publication_layer(db, domain=domain, history_limit=1)
    return _templates.TemplateResponse(
        request,
        "domain_console_overview.html",
        {
            **ctx,
            "entity_types": list(schema.get("entity_types") or []),
            "relationship_kinds": list(schema.get("relationship_kinds") or []),
            "curation": curation,
            "publication": publication,
            "pending_count": bench_proposals.count_pending(db, domain_key=domain_key),
            "my_tasks": sorted_tasks(
                bench_authoring.authoring_list_tasks(
                    db, domain_id=domain["id"], assignee=user.sub
                )
            ),
            # 「谁在跑」：两类执行方各取最近一轮，各自留空态。合成一句「最近活动」
            # 会把「舰队从没动过」说成「有人在跑」——那是两个不同的判断。
            "who_runs": {
                origin: (agent_runs.list_runs(
                    db, domain_key=domain_key, origin=origin, limit=1
                ) or [None])[0]
                for origin in ("kernel", "fleet")
            },
            "recent_events": curation.get("recent_events") or [],
        },
    )


# ----------------------------------------------------------------- ontology #


@read_only_router.get(
    "/d/{domain_key}/ontology", include_in_schema=False, name="console_ontology",
    dependencies=_READ_GATES,
)
def console_ontology(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The ontology ledger **and** its editing surface.

    The ledger answers "what is declared vs what is curated"; the editing parts
    answer "put something in". Both live here because a page that reports an
    empty ontology without offering a way to fill it is a dead end.

    ``kind`` / ``q`` / ``deleted`` are list filters; the write forms render only
    when ``cap.can_write``.
    """
    from ...bench import ontology_import

    domain = resolve_domain(db, domain_key)
    ledger = bench_ledger.ledger(db, domain=domain)
    cap = capability(db, domain, user)
    kind = (request.query_params.get("kind") or "").strip() or None
    query = (request.query_params.get("q") or "").strip() or None
    show_deleted = (request.query_params.get("deleted") or "") == "1"
    units = bench_authoring.authoring_list_units(
        db, domain_key=domain_key, kind=kind, query=query,
        include_deleted=show_deleted, limit=200,
    )
    live_entities = bench_authoring.authoring_live_entities(db, domain_key=domain_key)
    # Declared-but-empty types and smoke leftovers are different facts: the first
    # is a coverage gap, the second is junk that should be cleaned. Showing them
    # as one list would invite "just delete the gaps".
    declared = (ledger["declaration"] or {}).get("entity_types") or []
    used = {u["kind"] for u in units if not (u.get("tags") or {}).get("deleted")}
    vocab_gaps = [k for k in declared if k not in used]
    smoke = [u for u in units if ontology_import.is_smoke(u)]
    return _templates.TemplateResponse(
        request,
        "domain_console_ontology.html",
        {
            **console_context(db, domain, user),
            **ledger,
            "units": units,
            "live_entities": live_entities,
            "vocab_gaps": vocab_gaps,
            "smoke_units": smoke,
            "filters": {"kind": kind or "", "q": query or "", "deleted": show_deleted},
            "entity_types": (ledger["declaration"] or {}).get("entity_types") or [],
            "relationship_kinds": (ledger["declaration"] or {}).get("relationship_kinds") or [],
            "events": bench_authoring.authoring_events_for(
                db, domain_id=domain["id"], limit=20
            ),
            "graph": _ontology_graph(units),
            "grounding": _grounding_map(units),
        },
    )


def _grounding_map(units: list[dict]) -> dict:
    """Per-unit "what this rests on", keyed by the unit's external key.

    Built once for the page rather than one lookup per row: with a few dozen
    units the difference is latency, with a few hundred it is whether the page
    loads at all. Only relationship units carry endpoints, so this is a single
    pass over the list the page already has.
    """
    out: dict[str, list[dict]] = {}
    for unit in units:
        attrs = unit.get("attrs") or {}
        frm, to = attrs.get("from_key"), attrs.get("to_key")
        if not frm or not to:
            continue
        out.setdefault(frm, []).append({"kind": unit["kind"], "other": to, "direction": "out"})
        out.setdefault(to, []).append({"kind": unit["kind"], "other": frm, "direction": "in"})
    return out


def _ontology_graph(units: list[dict], *, limit: int = 60) -> dict:
    """Two-column node/edge projection for the graph view.

    Concepts on one side, documents (laws, clauses) on the other, edges being the
    relationships between them. Deterministic ordering (by kind then key) so the
    same ontology always draws the same picture — a graph that reshuffles on
    reload cannot be read as a structure.

    Anything without an edge is returned as ``isolated``: an ungrounded unit is
    the single most useful thing this view can show, and drawing it floating in
    space would hide it.
    """
    live = [u for u in units if not (u.get("tags") or {}).get("deleted")]
    # A unit with both endpoints *is* an edge. Deciding by shape rather than by
    # a kind name keeps this independent of the domain's vocabulary — and stops
    # a relationship from being drawn as a node (which it did at first).
    edge_units = [u for u in live if (u.get("attrs") or {}).get("from_key")
                  and (u.get("attrs") or {}).get("to_key")]
    node_units = [u for u in live if u not in edge_units]
    nodes = sorted(node_units, key=lambda u: (u["kind"], u["external_key"]))[:limit]
    by_key = {u["external_key"]: u for u in nodes}
    edges: list[dict] = []
    linked: set[str] = set()
    for unit in edge_units:
        attrs = unit.get("attrs") or {}
        frm, to = attrs.get("from_key"), attrs.get("to_key")
        if frm in by_key and to in by_key:
            edges.append({"from": frm, "to": to, "kind": unit["kind"]})
            linked.update((frm, to))
    concepts = [u for u in nodes if u["kind"] == "concept"]
    documents = [u for u in nodes if u["kind"] != "concept"]
    return {
        "concepts": concepts,
        "documents": documents,
        "edges": edges,
        "isolated": [u for u in nodes if u["external_key"] not in linked],
        "truncated": len(node_units) > limit,
        "limit": limit,
    }


# -------------------------------------------------------------- ontology writes #


def _ontology_redirect(domain_key: str, msg: str, err: bool = False, **interp):
    return _flash(f"/d/{quote(domain_key)}/ontology", msg, err=err, **interp)


@write_router.post(
    "/d/{domain_key}/ontology/units", include_in_schema=False,
    name="console_ontology_unit_write",
    dependencies=[Depends(require_scope("content:write"))],
)
async def console_ontology_unit_write(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create or update one entity. All writes go through the kernel.

    ``create`` vs ``update`` is decided by whether the unit exists — the same
    rule the kernel uses to label its event, so the page cannot claim "created"
    for something that was overwritten.
    """
    domain = resolve_domain(db, domain_key)
    cap = capability(db, domain, user)
    if not cap["can_write"]:
        raise HTTPException(status_code=403, detail="write requires expert or above")
    form = await request.form()
    kind = (form.get("kind") or "").strip()
    key = (form.get("external_key") or "").strip()
    body = (form.get("body") or "").strip()
    operator = user.email or user.name or user.sub
    existed = bench_authoring.authoring_get_unit(
        db, domain_key=domain_key, kind=kind, external_key=key
    )
    try:
        if existed:
            bench_authoring.authoring_update_unit(
                db, domain_key=domain_key, kind=kind, external_key=key,
                body=body, operator=operator,
            )
        else:
            bench_authoring.authoring_create_unit(
                db, domain_key=domain_key, kind=kind, external_key=key,
                body=body, operator=operator,
            )
    except ValueError as exc:
        return _ontology_redirect(domain_key, "flash.ontology_write_failed",
                                  err=True, detail=str(exc))
    return _ontology_redirect(
        domain_key, "flash.ontology_unit_saved", key=key,
        op="updated" if existed else "created",
    )


@write_router.post(
    "/d/{domain_key}/ontology/units/delete", include_in_schema=False,
    name="console_ontology_unit_delete",
    dependencies=[Depends(require_scope("content:write"))],
)
async def console_ontology_unit_delete(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Soft-delete one unit. Deleting is a lead action: it is a semantic asset.

    Relationships are **not** cascaded — a cascade would silently widen the blast
    radius. The page shows how many relations referenced the entity, and those
    relations become visibly dangling instead of vanishing.
    """
    domain = resolve_domain(db, domain_key)
    cap = capability(db, domain, user)
    if not cap["can_assign"]:
        raise HTTPException(status_code=403, detail="deleting requires the domain lead")
    form = await request.form()
    kind = (form.get("kind") or "").strip()
    key = (form.get("external_key") or "").strip()
    detail = bench_authoring.authoring_unit_detail(
        db, domain_key=domain_key, kind=kind, external_key=key
    )
    try:
        bench_authoring.authoring_delete_unit(
            db, domain_key=domain_key, kind=kind, external_key=key,
            operator=user.email or user.name or user.sub,
        )
    except ValueError as exc:
        return _ontology_redirect(domain_key, "flash.ontology_write_failed",
                                  err=True, detail=str(exc))
    return _ontology_redirect(
        domain_key, "flash.ontology_unit_deleted", key=key,
        related=len((detail or {}).get("related") or []),
    )


@write_router.post(
    "/d/{domain_key}/ontology/relations", include_in_schema=False,
    name="console_ontology_relation_create",
    dependencies=[Depends(require_scope("content:write"))],
)
async def console_ontology_relation_create(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a relationship between two entities that exist right now.

    Endpoints arrive as ``external_key`` values chosen from the picker; they are
    re-resolved here so a hand-edited form cannot point at a deleted or invented
    entity.
    """
    domain = resolve_domain(db, domain_key)
    cap = capability(db, domain, user)
    if not cap["can_write"]:
        raise HTTPException(status_code=403, detail="write requires expert or above")
    form = await request.form()
    kind = (form.get("kind") or "").strip()
    from_key = (form.get("from_key") or "").strip()
    to_key = (form.get("to_key") or "").strip()
    body = (form.get("body") or "").strip() or f"{from_key} {kind} {to_key}"
    live = {
        e["external_key"]
        for e in bench_authoring.authoring_live_entities(db, domain_key=domain_key)
    }
    for label, key in (("from", from_key), ("to", to_key)):
        if key not in live:
            return _ontology_redirect(
                domain_key, "flash.ontology_write_failed", err=True,
                detail=f"{label} endpoint {key!r} is not a live entity of this domain",
            )
    try:
        bench_authoring.authoring_create_relationship(
            db, domain_key=domain_key, kind=kind, from_key=from_key,
            to_key=to_key, body=body,
            operator=user.email or user.name or user.sub,
        )
    except ValueError as exc:
        return _ontology_redirect(domain_key, "flash.ontology_write_failed",
                                  err=True, detail=str(exc))
    return _ontology_redirect(
        domain_key, "flash.ontology_relation_saved", kind=kind,
        from_key=from_key, to_key=to_key,
    )


@write_router.post(
    "/d/{domain_key}/ontology/import", include_in_schema=False,
    name="console_ontology_import",
    dependencies=[Depends(require_scope("content:write"))],
)
async def console_ontology_import(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Bulk import: ``dry=1`` previews every row; otherwise it writes them.

    Both modes call the same planner, so the preview cannot promise something the
    write refuses. The preview is the default when the flag is absent **for
    humans** — an accidental Enter must not write 200 units — so only an explicit
    ``dry=0`` (or the confirm button) writes.
    """
    from ...bench import ontology_import

    domain = resolve_domain(db, domain_key)
    cap = capability(db, domain, user)
    if not cap["can_write"]:
        raise HTTPException(status_code=403, detail="import requires expert or above")
    form = await request.form()
    raw = (form.get("payload") or "").strip()
    dry = (form.get("dry") or "1").strip() not in ("0", "false", "no")
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        return _ontology_redirect(domain_key, "flash.ontology_import_failed",
                                  err=True, detail=f"payload is not JSON: {exc}")
    try:
        planned = ontology_import.plan(db, domain_key=domain_key, payload=payload)
    except ontology_import.ImportPayloadError as exc:
        return _ontology_redirect(domain_key, "flash.ontology_import_failed",
                                  err=True, detail=str(exc))
    if dry:
        summary = ontology_import.summarise(planned)
        return _templates.TemplateResponse(
            request,
            "domain_console_ontology_import.html",
            {
                **console_context(db, domain, user),
                "summary": summary,
                "payload": raw,
                "dry": True,
            },
        )
    result = ontology_import.apply(
        db, domain_key=domain_key, rows=planned,
        operator=user.email or user.name or user.sub,
    )
    return _templates.TemplateResponse(
        request,
        "domain_console_ontology_import.html",
        {
            **console_context(db, domain, user),
            "summary": result,
            "payload": raw,
            "dry": False,
        },
    )


# -------------------------------------------------------------------- inbox #


@read_only_router.get(
    "/d/{domain_key}/inbox", include_in_schema=False, name="console_inbox",
    dependencies=_READ_GATES,
)
def console_inbox(
    request: Request,
    domain_key: str,
    state: Optional[str] = None,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The domain's proposal inbox, optionally filtered by state."""
    domain = resolve_domain(db, domain_key)
    batch = (request.query_params.get("batch") or "").strip() or None
    try:
        proposals = bench_proposals.list_proposals(
            db, domain_key=domain_key, state=state, batch=batch
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Dispatched work must be visible to *someone*: the overview only lists tasks
    # whose assignee string equals the caller's id, and a batch dispatch assigns
    # free-text identities (a person's email, a fleet). Without this list the
    # tasks exist, block re-dispatch (idempotency), and nobody can see or close
    # them.
    tasks = bench_authoring.authoring_list_tasks(db, domain_id=domain["id"])
    # 来源列要显示「解析后的来源」，不是一串原始标识：只写 `fleet:<id>/<post>`
    # 时复核的人看不出这是哪支舰队、登记还在不在。未解析的显式标 legacy。
    source_views = bench_proposals.describe_sources(
        db, sources=[p["source"] for p in proposals], domain_key=domain_key
    )
    return _templates.TemplateResponse(
        request,
        "domain_console_inbox.html",
        {
            **console_context(db, domain, user),
            "proposals": proposals,
            "source_views": source_views,
            "state_filter": state,
            "tasks": tasks,
            "open_tasks": [t for t in tasks if t["status"] in ("pending", "in_progress")],
            "batch": batch or "",
            "batches": bench_proposals.batches(db, domain_key=domain_key),
        },
    )


@write_router.post(
    "/d/{domain_key}/inbox/{proposal_id}/confirm", include_in_schema=False,
    name="console_inbox_confirm", dependencies=_LEAD_GATES,
)
def console_inbox_confirm(
    domain_key: str,
    proposal_id: int,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("content:write")),
):
    """Confirm one proposal into the ontology through the kernel write path.

    The submitter may not confirm their own proposal (the kernel enforces it;
    this route passes the platform-admin flag so an administrator's override is
    recorded explicitly in the proposal's event note).
    """
    back = f"/d/{quote(domain_key, safe='')}/inbox"
    try:
        bench_proposals.confirm(
            db,
            domain_key=domain_key,
            proposal_id=proposal_id,
            actor=_operator_of(user),
            admin_override=is_platform_admin(user),
        )
    except PermissionError as exc:
        return _flash(back, "console.flash.proposal_failed", err=True, detail=str(exc))
    except ValueError as exc:
        return _flash(back, "console.flash.proposal_failed", err=True, detail=str(exc))
    return _flash(back, "console.flash.proposal_confirmed")


@write_router.post(
    "/d/{domain_key}/inbox/{proposal_id}/reject", include_in_schema=False,
    name="console_inbox_reject", dependencies=_LEAD_GATES,
)
async def console_inbox_reject(
    request: Request,
    domain_key: str,
    proposal_id: int,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("content:write")),
):
    """Reject one proposal; a reason is required."""
    form = await request.form()
    note = str(form.get("note") or "").strip()
    back = f"/d/{quote(domain_key, safe='')}/inbox"
    try:
        bench_proposals.reject(
            db,
            domain_key=domain_key,
            proposal_id=proposal_id,
            actor=_operator_of(user),
            note=note,
        )
    except ValueError as exc:
        return _flash(back, "console.flash.proposal_failed", err=True, detail=str(exc))
    return _flash(back, "console.flash.proposal_rejected")


# ------------------------------------------------------------------ publish #


@read_only_router.get(
    "/d/{domain_key}/publish", include_in_schema=False, name="console_publish",
    dependencies=_READ_GATES,
)
def console_publish(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Release history, registered consumers and their pull footprints."""
    domain = resolve_domain(db, domain_key)
    return _templates.TemplateResponse(
        request,
        "domain_console_publish.html",
        {
            **console_context(db, domain, user),
            "publication": bench_ledger.publication_layer(db, domain=domain),
            "consumption": bench_ledger.consumption_layer(db, domain=domain),
        },
    )


@write_router.post(
    "/d/{domain_key}/publish", include_in_schema=False, name="console_publish_action",
    dependencies=_LEAD_GATES,
)
def console_publish_action(
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("content:write")),
):
    """Freeze the next immutable version through the existing publish function.

    No second publication implementation: this is ``distribution.publish_domain``
    (idempotent on an unchanged digest), so the ledger, the pull surface and the
    admin release page can only ever agree on what v{N} is.
    """
    back = f"/d/{quote(domain_key, safe='')}/publish"
    try:
        publication = bench_distribution.publish_domain(
            db, domain_key=domain_key, published_by=_operator_of(user)
        )
    except ValueError as exc:
        return _flash(back, "console.flash.publish_failed", err=True, detail=str(exc))
    return _flash(back, "console.flash.published", version=publication["version"])


# -------------------------------------------------------------------- bench #


@read_only_router.get(
    "/d/{domain_key}/eval-runs", include_in_schema=False, name="console_eval_runs",
    dependencies=_READ_GATES,
)
def console_eval_runs(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The domain's evaluation-asset shelf plus the unassigned pool.

    Renamed from ``bench`` when the console grew evaluation *standards* as their
    own area (add-domain-tree-and-shared-libraries §4): the assets/runs view is
    what ``bench`` always showed, and the old URL now 302s here.
    """
    domain = resolve_domain(db, domain_key)
    groups = bench_domain_assets.list_for_domain(db, domain_key=domain_key)
    has_orphans = any(
        not item["exists"]
        for group in groups["groups"]
        for item in group["items"]
    )
    from ...bench import lane as bench_lane

    lane_state = bench_lane.describe()
    return _templates.TemplateResponse(
        request,
        "domain_console_bench.html",
        {
            **console_context(db, domain, user),
            "groups": groups,
            "unassigned": bench_domain_assets.list_unassigned(
                db, domain_key=domain_key
            ),
            "has_orphans": has_orphans,
            # Whether the thing that evaluates can be reached at all. Without
            # this an empty run list reads as "nobody has evaluated yet", which
            # on 2026-11-09 was false in the worst way: the lane was dead and no
            # run had ever succeeded.
            "lane": lane_state,
        },
    )


@read_only_router.get(
    "/d/{domain_key}/bench", include_in_schema=False, name="console_bench_legacy",
)
def console_bench_legacy(domain_key: str):
    """Legacy ``bench`` URL → the renamed evaluation-runs area (302, never 404)."""
    return RedirectResponse(
        url=f"/d/{quote(domain_key, safe='')}/eval-runs", status_code=302
    )


# ------------------------------------------------------------- team view #


@read_only_router.get(
    "/d/{domain_key}/team", include_in_schema=False, name="console_team",
    dependencies=_READ_GATES,
)
def console_team(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """值班长一页：质量比 + 运行台账 + 按批待确认。

    三样东西必须同屏，因为它们是同一个判断的三个面：**哪里薄**（质量比）、
    **谁在跑、成没成**（台账）、**人该看什么**（按批的待确认）。分成三页，
    值班的人就得自己在脑子里拼。

    页面本身只读：确认/退回的按钮指向既有的 inbox 批量端点，权限仍由那条
    路由的 lead 闸判定——页面上看得见一个按钮，不代表点得动。
    """
    from ...bench import agent_runs, agent_team, proposals as bench_proposals, quality

    domain = resolve_domain(db, domain_key)
    cap = capability(db, domain, user)
    # The seventh ratio lives on the template, not on the corpus, so it is read
    # separately and handed in — the console must show "this domain cannot be
    # measured at all" next to the six ratios, or a ruler-less template looks
    # like a domain with healthy metrics.
    from ...bench import template_readiness

    anchored = db.execute(
        "SELECT schema FROM ontology_templates WHERE id = %s",
        (domain["template_id"],),
    ).fetchone()
    anchored_schema = (anchored or {}).get("schema") or {}
    if isinstance(anchored_schema, str):
        import json as _json
        anchored_schema = _json.loads(anchored_schema)
    metrics = quality.all_metrics(
        db, domain_key=domain_key, namespace=domain["path"],
        template_readiness=template_readiness.readiness(
            db, domain_path=domain["path"], schema=anchored_schema
        ),
    )
    thresholds = dict(quality.QUALITY_THRESHOLDS)
    review = metrics.get("review_lag") or {}
    batches = [
        b for b in bench_proposals.batches(db, domain_key=domain_key)
        if b.get("pending")
    ]
    # 工单在团队区与工单页同源：**同一次查询**，不另写一份口径。值班的人先看
    # 「谁在跑」，紧接着要问「还有谁该跑」，中间不该跳页。
    open_orders = [
        t for t in bench_authoring.authoring_list_tasks(db, domain_id=domain["id"])
        if t["status"] in ("pending", "in_progress")
    ]
    return _templates.TemplateResponse(
        request,
        "domain_console_team.html",
        {
            **console_context(db, domain, user),
            "cap": cap,
            "metrics": metrics,
            "thresholds": thresholds,
            "review": review,
            "ledger": agent_runs.summary(db, domain_key=domain_key),
            "runs": agent_runs.list_runs(db, domain_key=domain_key, limit=20),
            "batches": batches,
            "open_orders": open_orders,
            "order_counts": {
                kind: sum(1 for t in open_orders if t.get("assignee_kind") == kind)
                for kind in bench_authoring.ASSIGNEE_KINDS
            },
            "plan": agent_team.plan(domain_key),
        },
    )


# ------------------------------------------------------- work orders view #


@read_only_router.get(
    "/d/{domain_key}/work-orders", include_in_schema=False, name="console_work_orders",
    dependencies=_READ_GATES,
)
def console_work_orders(
    request: Request,
    domain_key: str,
    status: Optional[str] = None,
    kind: Optional[str] = None,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The domain's work orders, filterable by state and assignee kind.

    Why this page exists separately from the overview's "my tasks": that list
    matches ``assignee == user.sub``, which is *one* of three kinds. A work order
    handed to a kernel role or a fleet is invisible there — it exists, blocks
    re-dispatch, and nobody can see or close it. The kind is therefore a first
    class filter, not a decoration: "who is this waiting on" is the question the
    page answers.
    """
    from ...bench import dispatch as bench_dispatch

    domain = resolve_domain(db, domain_key)
    cap = capability(db, domain, user)
    if status is not None and status not in ("pending", "in_progress", "done", "cancelled"):
        raise HTTPException(status_code=422, detail=f"未知状态：{status!r}")
    if kind is not None and kind not in bench_authoring.ASSIGNEE_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"未知指派人档位：{kind!r}（可用：{list(bench_authoring.ASSIGNEE_KINDS)}）",
        )

    tasks = bench_authoring.authoring_list_tasks(
        db, domain_id=domain["id"], status=status
    )
    if kind is not None:
        tasks = [t for t in tasks if t.get("assignee_kind") == kind]

    # 每行带一句「它在等谁」：三档的后果不同，同一个「已派出」会把等待舰队认领
    # 说成「下一轮就跑了」，值班的人据此判断要不要催。
    for task in tasks:
        task["consequence"] = _consequence_key(task)
        task["trail"] = [e for e in (task.get("transitions") or []) if e.get("from")]

    return _templates.TemplateResponse(
        request,
        "domain_work_orders.html",
        {
            **console_context(db, domain, user),
            "cap": cap,
            "tasks": tasks,
            "status_filter": status,
            "kind_filter": kind,
            "kinds": bench_authoring.ASSIGNEE_KINDS,
            "route_hint": {
                gap: bench_dispatch.route_for(gap) for gap in bench_dispatch.GAP_TASKS
            },
        },
    )


def _consequence_key(task: dict) -> str:
    """What the assignee kind actually means for this task's next move.

    Three kinds, three different sentences — sharing one "dispatched" wording
    would state something false about two of them.
    """
    kind = task.get("assignee_kind") or "human"
    return {
        "kernel-role": "consequence_kernel",
        "fleet": "consequence_fleet",
    }.get(kind, "consequence_human")


# ------------------------------------------------------- corpus documents #

#: Browse page size. The store holds tens of thousands of documents; a page that
#: tried to show them at once would be a different product (and an unusable one).
_LIBRARY_PAGE = 25


def _library_redirect(domain_key: str, msg: str, err: bool = False, **interp):
    return _flash(f"/d/{quote(domain_key)}/library", msg, err=err, **interp)


@read_only_router.get(
    "/d/{domain_key}/library", include_in_schema=False, name="console_library",
    dependencies=_READ_GATES,
)
def console_library(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The documents this domain can draw from — by document, not by chunk.

    Retrieval answers "what is similar to this sentence"; this page answers
    "which documents does the corpus hold, and which of them have I taken in".
    Both read the same subscriptions, so the browse scope cannot exceed what a
    search would honour.
    """
    from ...bench import corpus_catalog

    domain = resolve_domain(db, domain_key)
    try:
        scope = library_store.effective_sources(db, domain_path=domain["path"])
    except ValueError as exc:  # a subscription that would widen its parent's scope
        scope = {}
        scope_error = str(exc)
    else:
        scope_error = None

    catalog: list[dict] = []
    for lib_key, allowed in scope.items():
        row = library_store.get_library(db, library_key=lib_key)
        if row is None:
            continue
        sources = []
        for src in library_store.list_sources(db, library_id=row["id"]):
            if allowed and src["source_key"] not in allowed:
                continue
            try:
                corpus_catalog.document_mapping(src)
                declared = True
            except corpus_catalog.DocumentMappingError:
                declared = False
            sources.append({**src, "document_declared": declared})
        catalog.append({**row, "sources": sources})

    lib_key = (request.query_params.get("lib") or "").strip() or None
    if lib_key is None and catalog:
        lib_key = catalog[0]["library_key"]
    src_key = (request.query_params.get("src") or "").strip() or None
    q = (request.query_params.get("q") or "").strip()
    try:
        offset = max(0, int(request.query_params.get("offset") or 0))
    except ValueError:
        offset = 0

    page = None
    page_error = None
    if lib_key:
        try:
            page = corpus_catalog.documents(
                db, library_key=lib_key, source_key=src_key, offset=offset,
                limit=_LIBRARY_PAGE, q=q, domain_key=domain_key,
            )
        except (corpus_catalog.DocumentMappingError, corpus_catalog.StoreError,
                ValueError) as exc:
            page_error = f"{type(exc).__name__}: {exc}"

    return _templates.TemplateResponse(
        request,
        "domain_console_library.html",
        {
            **console_context(db, domain, user),
            "catalog": catalog,
            "scope_error": scope_error,
            "lib_key": lib_key,
            "src_key": src_key or "",
            "q": q,
            "offset": offset,
            "page_size": _LIBRARY_PAGE,
            "page": page,
            "page_error": page_error,
            "cap": capability(db, domain, user),
        },
    )


@write_router.post(
    "/d/{domain_key}/library/adopt", include_in_schema=False,
    name="console_library_adopt",
    dependencies=[Depends(require_scope("content:write"))],
)
async def console_library_adopt(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Take one corpus document into this domain's ontology."""
    from ...bench import corpus_catalog

    domain = resolve_domain(db, domain_key)
    cap = capability(db, domain, user)
    if not cap["can_write"]:
        raise HTTPException(status_code=403, detail="write requires expert or above")
    form = await request.form()
    lib_key = (form.get("lib") or "").strip()
    src_key = (form.get("src") or "").strip()
    doc_id = (form.get("doc") or "").strip()
    if not (lib_key and src_key and doc_id):
        return _library_redirect(domain_key, "flash.library_adopt_failed",
                                 err=True, detail="missing document reference")
    try:
        out = corpus_catalog.adopt_document(
            db, domain_key=domain_key, library_key=lib_key, source_key=src_key,
            doc_id=doc_id, operator=_operator_of(user),
        )
    except (corpus_catalog.DocumentMappingError, corpus_catalog.StoreError,
            ValueError) as exc:
        return _library_redirect(domain_key, "flash.library_adopt_failed",
                                 err=True, detail=str(exc))
    return _library_redirect(
        domain_key, "flash.library_document_saved", key=out["key"],
        op="created" if out["created"] else "already",
        lib=lib_key, src=src_key,
    )


@write_router.post(
    "/d/{domain_key}/library/clauses", include_in_schema=False,
    name="console_library_clauses",
    dependencies=[Depends(require_scope("content:write"))],
)
async def console_library_clauses(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Take one document's articles in as clause units (one transaction)."""
    from ...bench import corpus_catalog

    domain = resolve_domain(db, domain_key)
    cap = capability(db, domain, user)
    if not cap["can_write"]:
        raise HTTPException(status_code=403, detail="write requires expert or above")
    form = await request.form()
    lib_key = (form.get("lib") or "").strip()
    src_key = (form.get("src") or "").strip()
    doc_id = (form.get("doc") or "").strip()
    law_key = (form.get("law_key") or "").strip() or None
    if not (lib_key and src_key and doc_id):
        return _library_redirect(domain_key, "flash.library_adopt_failed",
                                 err=True, detail="missing document reference")
    try:
        out = corpus_catalog.adopt_clauses(
            db, domain_key=domain_key, library_key=lib_key, source_key=src_key,
            doc_id=doc_id, operator=_operator_of(user), law_key=law_key,
        )
    except (corpus_catalog.DocumentMappingError, corpus_catalog.StoreError,
            ValueError) as exc:
        return _library_redirect(domain_key, "flash.library_adopt_failed",
                                 err=True, detail=str(exc))
    if not out["adopted"]:
        return _library_redirect(domain_key, "flash.library_no_clauses",
                                 err=True, detail=out.get("reason") or "",
                                 lib=lib_key, src=src_key)
    return _library_redirect(
        domain_key, "flash.library_clauses_saved", key=out["key"],
        n=out["adopted"], remaining=out["remaining"],
        lib=lib_key, src=src_key,
    )


# --------------------------------------------------------------- knowledge #


@read_only_router.get(
    "/d/{domain_key}/knowledge", include_in_schema=False, name="console_knowledge",
    dependencies=_READ_GATES,
)
def console_knowledge(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The corpus this domain can actually retrieve from, with its provenance.

    The scope is resolved by the same function retrieval uses
    (``library_index.explain_scope``), so the page cannot claim a range the
    search would not honour.
    """
    domain = resolve_domain(db, domain_key)
    # Retrieval lives here, next to the scope it obeys: the search box on this
    # page calls the same resolver the filter uses, so what the page says the
    # domain can see is exactly what a query can return. Before this existed the
    # registered corpora (364,916 law chunks) were reachable by no screen at all.
    q = (request.query_params.get("q") or "").strip()
    hits: list[dict] = []
    search_error = None
    if q:
        try:
            hits = library_index.search(db, domain_path=domain["path"], query=q, top_k=10)
        except library_index.NotSubscribed as exc:
            search_error = str(exc)
        except Exception as exc:  # an unreachable store is an error, not "no match"
            search_error = f"{type(exc).__name__}: {exc}"
    # What this domain *declares* it needs vs what its scope actually grants.
    # The declaration is the only place a domain states intent, so drift here is
    # the drift worth showing: a declared source nobody subscribed is invisible
    # everywhere else.
    from ...bench import declarations as bench_declarations
    from ...bench import templates as bench_templates

    decl = {}
    tmpl = bench_templates.get_template_by_id(db, template_id=domain["template_id"])
    if tmpl:
        decl = (tmpl.get("schema") or {}).get("corpus_declaration") or {}
    try:
        declared = bench_declarations.resolve(
            db, domain_path=domain["path"], decl=decl
        )
    except ValueError as exc:
        declared = {"entries": [], "missing": [], "error": str(exc), "all_satisfied": False}
    try:
        scope = library_index.explain_scope(db, domain_path=domain["path"])
        # How much content each library holds for this domain, counted through
        # the same resolver the search uses (an external library is counted in
        # its own store). "36 万块" has to be measured — a source count that
        # happens to look green is exactly what this page exists to prevent.
        chain = library_index._scope_paths(domain["path"])
        for lib in scope["libraries"]:
            # Per-source volume first: it is what the page shows, and it is also
            # where the total comes from. Counting the library separately would
            # be a second exact scan of the same store (~0.9s each) and a second
            # source of truth for one number.
            row = library_store.get_library(db, library_key=lib["library_key"])
            granted = set(lib["sources"])
            lib["chunks"] = None
            if row is not None:
                try:
                    lib["source_counts"] = library_index.source_counts(
                        db, lib=row, allowed=granted
                    )
                except Exception as exc:
                    lib["source_counts"] = {}
                    scope.setdefault("count_error", f"{lib['library_key']}: {exc}")
                if lib["source_counts"]:
                    lib["chunks"] = sum(lib["source_counts"].values())
                else:
                    try:
                        lib["chunks"] = library_index.count_for(
                            db, lib=row, allowed=granted, chain=chain
                        )
                    except Exception as exc:
                        scope.setdefault("count_error", f"{lib['library_key']}: {exc}")
    except ValueError as exc:  # a stored subscription that would widen scope
        scope = {"domain_path": domain["path"], "libraries": [], "error": str(exc)}
    return _templates.TemplateResponse(
        request,
        "domain_console_knowledge.html",
        {
            **console_context(db, domain, user),
            "scope": scope,
            "libraries": library_store.list_libraries(db),
            "q": q,
            "hits": hits,
            "search_error": search_error,
            "declared": declared,
        },
    )


# --------------------------------------------------------- eval standards #


@read_only_router.get(
    "/d/{domain_key}/eval-standards", include_in_schema=False,
    name="console_eval_standards", dependencies=_READ_GATES,
)
def console_eval_standards(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Own rubrics plus the ones inherited by reference from ancestors."""
    domain = resolve_domain(db, domain_key)
    standards = domain_rubrics.effective_rubrics(db, domain_path=domain["path"])
    return _templates.TemplateResponse(
        request,
        "domain_console_eval_standards.html",
        {
            **console_context(db, domain, user),
            "standards": standards,
            "own": [s for s in standards if s["origin"] == "own"],
            "inherited": [s for s in standards if s["origin"] == "inherited"],
        },
    )


@write_router.post(
    "/d/{domain_key}/bench/assign", include_in_schema=False,
    name="console_bench_assign", dependencies=_LEAD_GATES,
)
async def console_bench_assign(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("content:write")),
):
    """Add one asset to this domain's shelf (a directory entry, never a copy)."""
    form = await request.form()
    back = f"/d/{quote(domain_key, safe='')}/bench"
    try:
        bench_domain_assets.assign(
            db,
            domain_key=domain_key,
            asset_kind=str(form.get("asset_kind") or ""),
            asset_key=str(form.get("asset_key") or ""),
            added_by=_operator_of(user),
        )
    except ValueError as exc:
        return _flash(back, "console.flash.asset_failed", err=True, detail=str(exc))
    return _flash(back, "console.flash.asset_assigned")


@write_router.post(
    "/d/{domain_key}/bench/unassign", include_in_schema=False,
    name="console_bench_unassign", dependencies=_LEAD_GATES,
)
async def console_bench_unassign(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("content:write")),
):
    """Remove one directory entry; the asset itself is untouched."""
    form = await request.form()
    back = f"/d/{quote(domain_key, safe='')}/bench"
    bench_domain_assets.unassign(
        db,
        domain_key=domain_key,
        asset_kind=str(form.get("asset_kind") or ""),
        asset_key=str(form.get("asset_key") or ""),
    )
    return _flash(back, "console.flash.asset_unassigned")


@write_router.post(
    "/d/{domain_key}/bench/purge", include_in_schema=False,
    name="console_bench_purge", dependencies=_LEAD_GATES,
)
def console_bench_purge(
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("content:write")),
):
    """Drop directory rows whose asset no longer exists (orphans only)."""
    back = f"/d/{quote(domain_key, safe='')}/bench"
    try:
        bench_domain_assets.purge_orphans(db, domain_key=domain_key)
    except ValueError as exc:
        return _flash(back, "console.flash.asset_failed", err=True, detail=str(exc))
    return _flash(back, "console.flash.asset_unassigned")


# ----------------------------------------------------------------- settings #


@read_only_router.get(
    "/d/{domain_key}/settings", include_in_schema=False, name="console_settings",
    dependencies=_LEAD_GATES,
)
def console_settings(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """This domain's members and invitations (platform-level work stays in /admin)."""
    domain = resolve_domain(db, domain_key)
    ctx = console_context(db, domain, user)
    return _templates.TemplateResponse(
        request,
        "domain_console_settings.html",
        {
            **ctx,
            "members": workspaces.list_members(db, domain_id=domain["id"]),
            "invitations": workspaces.list_invitations(db, domain_id=domain["id"]),
        },
    )


# ------------------------------------------------- internal submit surface #
# The platform's own automation (the ontology fleet) and experts submit drafts
# here instead of pushing them into a consumer's approval queue. Platform
# self-closure is the point: production lands in the domain that owns it.


@write_router.post(
    "/api/d/{domain_key}/proposals", include_in_schema=False,
    name="console_proposal_submit", dependencies=_WRITE_GATES,
)
async def console_proposal_submit(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Submit one draft into the domain's inbox (idempotent on a pending key)."""
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="request body must be a JSON object")
    try:
        proposal, created = bench_proposals.submit(
            db,
            domain_key=domain_key,
            source=str(payload.get("source") or "").strip(),
            kind=str(payload.get("kind") or "").strip(),
            external_key=str(payload.get("external_key") or "").strip(),
            body=str(payload.get("body") or "").strip(),
            evidence=payload.get("evidence"),
            impact=str(payload.get("impact") or ""),
            submitted_by=str(payload.get("submitted_by") or "").strip()
            or _operator_of(user),
            with_created=True,
            # External channel, always. ``extract:`` sources are refused here
            # because their trust basis is that the pipeline is unreachable
            # from the network; this constant is the only thing saying so.
            via=bench_submitters.VIA_HTTP,
            # ``agent:``/``user:`` sources may only name the caller themselves.
            authenticated_as=_operator_of(user),
        )
    except bench_proposals.SubmitterRefused as exc:
        # 403, not 400: the request is well-formed; the caller is not allowed to
        # submit as that source.
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except bench_proposals.ProposalTargetExists as exc:
        # 会话面与机器面必须是同一个状态码：同一个条件（键已在库 / 端点未闭合）
        # 对人回 400、对舰队回 409，读起来就成了两件事。409 = 目标状态与这次提交
        # 冲突，请求本身没有写错。
        raise HTTPException(
            status_code=409,
            detail={"reason": exc.reason, "message": exc.detail, "hint": exc.hint},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "id": proposal["id"],
        "state": proposal["state"],
        "external_key": proposal["external_key"],
        "evidence_digest": proposal["evidence_digest"],
        # False = idempotent hit on the existing pending row. The submitting
        # fleet reports 新增 vs 幂等命中 from this flag; without it both look
        # identical and the round's count cannot be trusted.
        "created": created,
    }


@read_only_router.get(
    "/api/d/{domain_key}/proposals/outcomes", include_in_schema=False,
    name="console_proposal_outcomes",
    dependencies=[Depends(require_scope("content:read"))],
)
def console_proposal_outcomes(
    domain_key: str,
    source: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """What happened to the proposals this submitter filed in this domain.

    A submitter MUST see its own outcomes and nobody else's: the ``source`` is
    checked against the caller's identity (or admin), not trusted because it was
    passed in. Without this read face a fleet learns "rejected" only by being
    refused on resubmission — and never learns *why*.
    """
    resolve_domain(db, domain_key)  # 404 for an unknown domain, before any read
    wanted = (source or "").strip()
    _consumer, verdict = bench_distribution.resolve_submitter(
        db, source=wanted, domain_key=domain_key,
        via=bench_submitters.VIA_HTTP, authenticated_as=_operator_of(user),
    )
    if verdict != "ok" and not is_platform_admin(user):
        raise HTTPException(
            status_code=403,
            detail=f"只能读取自己来源的结局：{wanted!r}（{verdict}）",
        )
    return {
        "domain": domain_key,
        "source": wanted,
        "outcomes": bench_proposals.list_outcomes(
            db, source=wanted, domain_key=domain_key
        ),
    }


@read_only_router.get(
    "/api/d/{domain_key}/runs", include_in_schema=False,
    name="console_domain_runs",
    dependencies=[Depends(require_scope("content:read"))],
)
def console_domain_runs(
    domain_key: str,
    runner_ref: str | None = None,
    origin: str | None = None,
    limit: int = 50,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The ledger as a machine-readable read face (session channel).

    Why a JSON face exists at all: the team *page* shows runs to a human, but a
    submitter must be able to answer "did this round of mine land, and how did it
    end?" without parsing HTML. Without it a fleet's only feedback is silence —
    it writes back, gets 200, and never learns whether the row is there.

    Isolation is :func:`submitters.may_read_runner_ref`, the same predicate the
    machine-token twin under ``/api/v1/distribution`` uses: a fleet reads only
    its own rounds; a domain member (who already sees the whole ledger page) and
    an admin read the domain's. Asking for someone else's prefix is 403, not an
    empty list — an empty list would read as "your write-back did not land".
    """
    from ...bench import agent_runs as bench_agent_runs

    domain = resolve_domain(db, domain_key)  # 404 before any read
    wanted = (runner_ref or "").strip() or None
    admin = is_platform_admin(user)
    member = admin or workspaces.get_active_role(
        db, domain_id=domain["id"], user_id=user.sub
    ) is not None
    if not bench_submitters.may_read_runner_ref(
        wanted, is_member=member, is_admin=admin
    ):
        raise HTTPException(
            status_code=403,
            detail=f"只能读取自己来源的运行：runner_ref={wanted!r}",
        )
    return {
        "domain": domain_key,
        "runner_ref": wanted,
        "runs": bench_agent_runs.list_runs(
            db, domain_key=domain_key, origin=origin, runner_ref=wanted, limit=limit,
        ),
    }


@read_only_router.get(
    "/api/v1/distribution/legacy-sources", include_in_schema=False,
    name="console_legacy_sources",
    dependencies=[Depends(require_scope("content:read"))],
)
def console_legacy_sources(
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Sources admitted by the lenient window — the number that closes it.

    Admin only: this is the migration's control reading, not a browsing surface.
    ``mode`` is reported alongside so the operator sees whether enforcement is
    currently strict or lenient in this process.
    """
    if not is_platform_admin(user):
        raise HTTPException(status_code=403, detail="需要平台管理员")
    return {
        "mode": bench_proposals._submitter_mode(),
        "sources": bench_proposals.legacy_sources(db),
    }


# ---------------------------------------------------------------- crosswalks
#
# Two separate read faces, deliberately not merged into one response:
#
#   GET .../relations    — the entity's edges in the ontology graph
#   GET .../crosswalks   — its mapping assertions to other layers/systems
#
# A crosswalk is NOT an edge. Merging the two would put a mapping in a graph
# traversal, which is exactly what `ontology-authoring` forbids; and a reader who
# gets one blended list cannot tell "this entity participates in these
# relationships" from "this entity has been mapped outward".


def _crosswalk_rows(db, *, path: str, entity_key: Optional[str]) -> list[dict]:
    sql = (
        "SELECT external_key, body, attrs, tier, updated_at "
        "FROM knowledge_units WHERE namespace = %s AND kind = 'crosswalk' "
        "  AND (tags->>'deleted') IS NULL"
    )
    params: list = [path]
    if entity_key:
        sql += " AND external_key = %s"
        params.append(entity_key)
    sql += " ORDER BY external_key, updated_at DESC"
    out = []
    for row in db.execute(sql, tuple(params)).fetchall():
        attrs = row["attrs"] or {}
        out.append({
            "key": row["external_key"],
            "body": row["body"],
            "relation": attrs.get("relation"),
            "peer": attrs.get("peer"),
            "confidence": attrs.get("confidence"),
            "connectivity": attrs.get("connectivity"),
            "missing_states": _crosswalk().effective_missing_states(
                attrs.get("connectivity")
            ),
            "confirmed": _crosswalk().is_confirmed(attrs, threshold=None),
            "tier": row["tier"],
            "updated_at": row["updated_at"],
        })
    return out


def _crosswalk():
    from ...bench import crosswalk

    return crosswalk


@read_only_router.get(
    "/d/{domain_key}/crosswalks", include_in_schema=False,
    name="console_crosswalks",
    dependencies=[Depends(require_scope("content:read"))],
)
def console_crosswalks(
    request: Request,
    domain_key: str,
    entity: Optional[str] = None,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Mapping assertions, optionally narrowed to one entity.

    Distinct from ``.../relations``: this endpoint never returns edges, and that
    endpoint never returns crosswalks. Same entities, two different questions.
    """
    from ...bench import quality

    domain = resolve_domain(db, domain_key)
    capability(db, domain, user)
    path = domain.get("path") or domain["key"]
    return {
        "domain": domain_key,
        "entity": entity,
        "crosswalks": _crosswalk_rows(db, path=path, entity_key=entity),
        "gaps": quality.crosswalk_gaps(db, namespace=path),
    }


@read_only_router.get(
    "/d/{domain_key}/crosswalks/connectivity/{system}", include_in_schema=False,
    name="console_crosswalk_connectivity",
    dependencies=[Depends(require_scope("content:read"))],
)
def console_crosswalk_connectivity(
    request: Request,
    domain_key: str,
    system: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Three-state evidence for one external system, shaped like the ERP file.

    The shape mirrors `connector-status.json` (`integrations[].states.{catalog,
    executor_tests, live}.{ok,evidence}`) on purpose: the ERP-side generator can
    switch its source to this endpoint without changing its consumers, and a
    fallback to the local file stays byte-comparable.
    """
    crosswalk = _crosswalk()
    domain = resolve_domain(db, domain_key)
    capability(db, domain, user)
    path = domain.get("path") or domain["key"]

    states = {s: {"ok": False, "evidence": None} for s in crosswalk.CONNECTIVITY_STATES}
    bound_keys: list[str] = []
    for row in _crosswalk_rows(db, path=path, entity_key=None):
        peer = row.get("peer") or {}
        if peer.get("kind") != "external_id" or peer.get("system") != system:
            continue
        bound_keys.append(row["key"])
        for state, value in (row.get("connectivity") or {}).items():
            if state in states and isinstance(value, dict) and value.get("ok"):
                states[state] = {
                    "ok": True,
                    "evidence": value.get("evidence"),
                    "at": value.get("at"),
                }

    missing = [s for s in crosswalk.CONNECTIVITY_STATES if not states[s]["ok"]]
    return {
        "domain": domain_key,
        "system": system,
        "connected": not missing,
        "missing": missing,
        "states": states,
        "maps": bound_keys,
    }
