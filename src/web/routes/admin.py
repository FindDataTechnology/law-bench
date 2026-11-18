"""Admin-gate routes: ontology templates + domain workspaces (change
``add-ontology-template-and-workspaces``, design D5).

All pages are server-rendered Jinja following the ``pages.py`` flash+redirect
pattern. Enforcement is two-gated per the web-rbac delta: platform scope first
(``require_scope``, Logto is the only source of platform roles) then domain
role (``require_domain_role``, the workspace membership record is the only
source of domain roles):

- ``/admin/templates`` (list / detail / create / new version)  — ``admin`` scope only;
- ``/admin/domains`` (list / instantiate)                      — ``admin`` scope only;
- ``/admin/domains/{domain_key}`` + members + invitations      — ``content:read`` /
  ``content:write`` (operations) AND domain ``lead`` (admins bypass the domain
  check — the composition order lives in the route dependencies);
- ``/admin/invite/{token}`` (view) — NO auth: the invitee may not have an
  account yet, and the token itself is the capability (the DB stores only its
  SHA-256 digest, so the plaintext link is the single admission credential;
  see ``_EXEMPT_PREFIXES`` in ``src/web/auth/deps.py``). Accepting still
  requires a session — a logged-out accepter is redirected into the existing
  Logto login flow and comes back via its ``next`` parameter.

Invitation plaintext handling follows the API-key discipline in
``auth.py``: the token is generated with ``secrets.token_urlsafe(32)``, only
``hashlib.sha256(token).hexdigest()`` is persisted via ``workspaces
.create_invitation`` (token_hash=), and the full plaintext link is shown
exactly once — in the creation flash. It is never stored or re-displayed;
pending-invitation tables show a hash prefix only.

The data layer is ``src/bench/templates.py`` / ``src/bench/workspaces.py``
(kernel of change D1-D3); this module stays a thin web surface — the only
direct SQL is the read-only pending-invitations listing, which the data layer
does not expose.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..auth import session as session_store
from ..auth.deps import User, require_scope
from ..auth.domain_rbac import require_domain_role
from ..deps import DbConn, get_db
from ..templating import templates as _templates
from ...bench import declarations as bench_declarations
from ...bench import distribution as bench_distribution
from ...bench import templates as bench_templates
from ...bench import template_readiness as bench_template_readiness
from ...bench import workspaces

read_only_router = APIRouter(tags=["admin"])
write_router = APIRouter(tags=["admin"])

logger = logging.getLogger(__name__)


def _flash(
    path: str, msg: str, err: bool = False, status: int = 303, **interp
) -> RedirectResponse:
    """Redirect with a flash message — same contract as ``pages.py::_flash``.

    ``msg`` is a dotted i18n key resolved by ``base.html``'s ``tr`` helper;
    ``**interp`` values ride along as extra query params (the base template
    forwards ``name`` and ``detail`` into ``tr``, so interpolated flashes stay
    locale-independent in the URL). A raw (non-key) message passes through.
    """
    sep = "&" if "?" in path else "?"
    q = f"msg={quote(msg)}"
    if err:
        q += "&err=1"
    for key, val in interp.items():
        q += f"&{key}={quote(str(val))}"
    return RedirectResponse(f"{path}{sep}{q}", status_code=status)


def _operator_of(user: User) -> str:
    """Stable, readable operator stamp — same construction as review/promotion."""
    return user.email or user.name or user.sub


def _schema_from_form(raw: Any) -> tuple[Optional[dict], Optional[str]]:
    """Parse the schema JSON textarea; ``(schema, None)`` or ``(None, problem)``."""
    try:
        schema = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        return None, str(exc)
    if not isinstance(schema, dict):
        return None, "schema must be a JSON object"
    return schema, None


def _row_dict(row: Any, keys: tuple[str, ...]) -> dict:
    """Map one DB row onto ``keys`` (dict rows pass through, tuples zip)."""
    if isinstance(row, dict):
        return {k: row[k] for k in keys}
    return dict(zip(keys, tuple(row)))


def _expired_for_display(value: Any) -> bool:
    """Fail-closed expiry mirror of the data layer's check, for display only.

    The authoritative check runs inside ``workspaces.accept_invitation``; this
    only drives the "expired" badge and the neutral invalid state on the invite
    page, so it must agree with the kernel (unparseable -> expired).
    """
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return True
    else:
        return True
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc) < datetime.now(timezone.utc)


def _session_user(request: Request) -> Optional[dict]:
    """Cookie-session payload for the auth-exempt invite pages.

    ``/admin/invite/*`` is exempt from the app-level ``get_current_user`` (an
    invitee may not have an account yet), so the exempt-path sentinel would
    hide a perfectly valid session. These routes resolve the cookie session
    themselves — browser-only flow, no Bearer/API-key channel applies.
    """
    try:
        return session_store.get_session(request)
    except session_store.SessionError:
        return None


def _pending_invitations(conn: DbConn, domain_id: int) -> list[dict]:
    """Pending (unaccepted) invitations of a domain, newest first.

    Read-only direct query — the data layer exposes create/get/accept but not a
    listing. The token hash is NEVER returned in full to the template: only a
    12-char prefix (``token_prefix``) plus a display-only ``expired`` flag.
    """
    cols = ("role", "token_hash", "invited_by", "expires_at", "created_at")
    cur = conn.execute(
        "SELECT role, token_hash, invited_by, expires_at, created_at "
        "FROM domain_invitations WHERE domain_id = %s AND accepted_at IS NULL "
        "ORDER BY created_at DESC",
        (domain_id,),
    )
    invitations = []
    for row in cur.fetchall():
        inv = _row_dict(row, cols)
        inv["token_prefix"] = f"{str(inv['token_hash'])[:12]}…"
        inv["expired"] = _expired_for_display(inv["expires_at"])
        invitations.append(inv)
    return invitations


# ----------------------------------------------------------------- templates #
# Template management is platform-admin exclusive (design D5): the vocabularies
# shape every domain, so a lead has no business editing them.


@read_only_router.get(
    "/admin/templates", include_in_schema=False, name="admin_templates",
    dependencies=[Depends(require_scope("admin"))],
)
def admin_templates(request: Request, db: DbConn = Depends(get_db)):
    """Template list: one row per name with its latest version."""
    return _templates.TemplateResponse(
        request,
        "admin_templates.html",
        {"templates": bench_templates.list_templates(db)},
    )


@read_only_router.get(
    "/admin/templates/{name}", include_in_schema=False, name="admin_template_detail",
    dependencies=[Depends(require_scope("admin"))],
)
def admin_template_detail(request: Request, name: str, db: DbConn = Depends(get_db)):
    """Latest schema rendered readably + full version history + new-version form."""
    latest = bench_templates.get_template(db, name=name)
    if latest is None:
        raise HTTPException(status_code=404, detail=f"template {name!r} not found")
    versions = bench_templates.list_template_versions(db, name=name)
    schema = latest["schema"] or {}
    # Ruler resolution is reported, not enforced, on this page: save-time stays
    # permissive so a template can be built in steps. The gate that refuses a
    # ruler-less template is at instantiation, where a domain starts relying on it.
    readiness = bench_template_readiness.readiness(
        db, domain_path="", schema=schema
    )
    return _templates.TemplateResponse(
        request,
        "admin_template_detail.html",
        {
            "template": latest,
            "versions": versions,
            "schema": schema,
            "readiness": readiness,
            "schema_pretty": json.dumps(schema, ensure_ascii=False, indent=2),
            "corpus_pretty": json.dumps(
                schema.get("corpus_declaration") or {}, ensure_ascii=False, indent=2
            ),
        },
    )


@write_router.post(
    "/admin/templates", include_in_schema=False, name="admin_template_create",
)
async def admin_template_create(
    request: Request,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("admin")),
):
    """Create version 1 of a template from the list-page form."""
    form = await request.form()
    name = (form.get("name") or "").strip()
    schema, problem = _schema_from_form(form.get("schema"))
    if problem is not None:
        return _flash("/admin/templates", "flash.template_json_invalid", err=True, detail=problem)
    try:
        # A declaration naming a library source that does not exist is a promise
        # nobody can keep; refuse it here rather than discover it later as
        # "why is this domain still missing corpus".
        bench_declarations.check_refs(db, schema.get("corpus_declaration"))
        bench_templates.create_template(
            db, name=name, schema=schema, created_by=_operator_of(user)
        )
    except ValueError as exc:
        # create_template validates the three-part schema itself; its error
        # message names every missing/invalid item = the problem list.
        return _flash("/admin/templates", "flash.template_create_failed", err=True, detail=str(exc))
    return _flash(f"/admin/templates/{quote(name)}", "flash.template_created", name=name)


@write_router.post(
    "/admin/templates/{name}/versions", include_in_schema=False,
    name="admin_template_version_create",
)
async def admin_template_version_create(
    request: Request,
    name: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("admin")),
):
    """Append a new immutable version from the detail-page JSON textarea."""
    form = await request.form()
    schema, problem = _schema_from_form(form.get("schema"))
    if problem is not None:
        return _flash(
            f"/admin/templates/{quote(name)}", "flash.template_json_invalid",
            err=True, detail=problem,
        )
    try:
        bench_declarations.check_refs(db, schema.get("corpus_declaration"))
        # The version form is a promotion, not an edit: it passes the novelty
        # gate (a new version must not be worse than the last verdict) and the
        # two stored-version guards (external vocabulary is read-only here, and
        # a layer may not change between versions).
        bench_template_readiness.promote_template_via_gate(
            db, name=name, schema=schema, created_by=_operator_of(user)
        )
    except ValueError as exc:
        return _flash(
            f"/admin/templates/{quote(name)}", "flash.template_create_failed",
            err=True, detail=str(exc),
        )
    return _flash(f"/admin/templates/{quote(name)}", "flash.template_version_created")


# ------------------------------------------------------------------- domains #


@read_only_router.get(
    "/admin/domains", include_in_schema=False, name="admin_domains",
    dependencies=[Depends(require_scope("admin"))],
)
def admin_domains(request: Request, db: DbConn = Depends(get_db)):
    """All domains with their template anchor and active member count."""
    # The admin page is the full roll-call, archived included: this is where a
    # retired line is found again to restore it.
    domains = workspaces.list_domains(db, include_archived=True)
    counts = {
        d["id"]: len(workspaces.list_members(db, domain_id=d["id"])) for d in domains
    }
    return _templates.TemplateResponse(
        request,
        "admin_domains.html",
        {"domains": domains, "member_counts": counts, "roles": workspaces.ROLES},
    )


@write_router.post("/admin/domains", include_in_schema=False, name="admin_domain_create")
async def admin_domain_create(
    request: Request,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("admin")),
):
    """Instantiate a domain from a template (latest or pinned version)."""
    form = await request.form()
    key = (form.get("key") or "").strip()
    name = (form.get("name") or "").strip()
    template_name = (form.get("template_name") or "").strip()
    version_raw = (form.get("template_version") or "").strip()
    try:
        version = int(version_raw) if version_raw else None
        created = workspaces.instantiate_domain(
            db,
            key=key,
            name=name,
            template_name=template_name,
            template_version=version,
            created_by=_operator_of(user),
        )
    except (ValueError, TypeError) as exc:
        return _flash("/admin/domains", "flash.domain_create_failed", err=True, detail=str(exc))
    return _flash(
        f"/admin/domains/{quote(created['key'])}", "flash.domain_created", name=name
    )


@read_only_router.get(
    "/admin/domains/{domain_key}", include_in_schema=False, name="admin_domain_detail",
    dependencies=[
        Depends(require_scope("content:read")),
        Depends(require_domain_role("lead")),
    ],
)
def admin_domain_detail(
    request: Request, domain_key: str, db: DbConn = Depends(get_db)
):
    """Domain workspace: info, publish/pull, members, member ops, invitations.

    ``require_domain_role("lead")`` above is the fail-closed gate: a non-member
    (or sub-lead member) is rejected with 403 「无该域权限」 before this handler
    runs, and the domain's existence is never disguised as a 404. Admins bypass
    the domain check, so ``domain is None`` here is only reachable by an admin
    typo and returns an honest 404.

    The 发布 (publish/pull) panel's listing comes from the distribution kernel
    (change add-knowledge-distribution-contract): this handler owns the page
    context; the publish POST itself lives in ``routes/distribution.py``.

    The RAG 语料 panel (change add-domain-rag-corpus-service, design D5) shows
    the domain's registered corpus (``src.search.resolver.get_corpus``); the
    register/ingest POSTs live in this module. The fetch is fail-safe display
    sugar (same contract as the chrome's ``my_domains``): a resolver/DB hiccup
    renders the "not registered" state instead of taking the whole domain page
    down — the register POST below is where real errors surface.
    """
    domain = workspaces.get_domain(db, domain_key=domain_key)
    if domain is None:
        raise HTTPException(status_code=404, detail=f"domain {domain_key!r} not found")
    members = workspaces.list_members(db, domain_id=domain["id"])
    publications = sorted(
        bench_distribution.list_publications(db, domain_key=domain_key),
        key=lambda p: p.get("version") or 0,
        reverse=True,
    )
    rag_corpus: Optional[dict] = None
    try:
        from src.search.resolver import get_corpus  # lazy: kernel import

        rag_corpus = get_corpus(db, domain_key=domain_key)
    except Exception:  # noqa: BLE001 - display sugar must not take the page down
        rag_corpus = None
    return _templates.TemplateResponse(
        request,
        "admin_domain_detail.html",
        {
            "domain": domain,
            "members": members,
            "invitations": _pending_invitations(db, domain["id"]),
            "publications": publications,
            "latest_publication": publications[0] if publications else None,
            "roles": workspaces.ROLES,
            "rag_corpus": rag_corpus,
            "rag_index_value": (rag_corpus or {}).get("index_name") or "",
            "rag_embedding_value": (rag_corpus or {}).get("embedding_model") or "",
            "rag_sources_pretty": json.dumps(
                (rag_corpus or {}).get("sources") or [], ensure_ascii=False, indent=2
            ),
        },
    )


def _back_to_domain(domain_key: str) -> str:
    return f"/admin/domains/{quote(domain_key)}"


@write_router.post(
    "/admin/domains/{domain_key}/members/add", include_in_schema=False,
    name="admin_member_add",
    dependencies=[
        Depends(require_scope("content:write")),
        Depends(require_domain_role("lead")),
    ],
)
async def admin_member_add(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("content:write")),
):
    """Add/replace a membership — content:write scope AND this domain's lead."""
    domain = workspaces.get_domain(db, domain_key=domain_key)
    if domain is None:
        raise HTTPException(status_code=404, detail=f"domain {domain_key!r} not found")
    form = await request.form()
    target = (form.get("user_id") or "").strip()
    role = (form.get("role") or "").strip()
    back = _back_to_domain(domain_key)
    try:
        workspaces.add_member(
            db, domain_id=domain["id"], user_id=target, role=role,
            added_by=_operator_of(user),
        )
    except ValueError as exc:
        return _flash(back, "flash.member_op_failed", err=True, detail=str(exc))
    return _flash(back, "flash.member_added", name=target)


@write_router.post(
    "/admin/domains/{domain_key}/members/role", include_in_schema=False,
    name="admin_member_role",
    dependencies=[
        Depends(require_scope("content:write")),
        Depends(require_domain_role("lead")),
    ],
)
async def admin_member_role(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("content:write")),
):
    """Change a member's role (append-only: the old row is retired, not edited)."""
    domain = workspaces.get_domain(db, domain_key=domain_key)
    if domain is None:
        raise HTTPException(status_code=404, detail=f"domain {domain_key!r} not found")
    form = await request.form()
    target = (form.get("user_id") or "").strip()
    role = (form.get("role") or "").strip()
    back = _back_to_domain(domain_key)
    try:
        workspaces.change_member_role(
            db, domain_id=domain["id"], user_id=target, role=role,
            changed_by=_operator_of(user),
        )
    except ValueError as exc:
        return _flash(back, "flash.member_op_failed", err=True, detail=str(exc))
    return _flash(back, "flash.member_role_changed", name=target)


@write_router.post(
    "/admin/domains/{domain_key}/members/remove", include_in_schema=False,
    name="admin_member_remove",
    dependencies=[
        Depends(require_scope("content:write")),
        Depends(require_domain_role("lead")),
    ],
)
async def admin_member_remove(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("content:write")),
):
    """Retire a membership — the member loses all access immediately."""
    domain = workspaces.get_domain(db, domain_key=domain_key)
    if domain is None:
        raise HTTPException(status_code=404, detail=f"domain {domain_key!r} not found")
    form = await request.form()
    target = (form.get("user_id") or "").strip()
    back = _back_to_domain(domain_key)
    workspaces.remove_member(
        db, domain_id=domain["id"], user_id=target, removed_by=_operator_of(user)
    )
    return _flash(back, "flash.member_removed", name=target)


@write_router.post(
    "/admin/domains/{domain_key}/invitations", include_in_schema=False,
    name="admin_invitation_create",
    dependencies=[
        Depends(require_scope("content:write")),
        Depends(require_domain_role("lead")),
    ],
)
async def admin_invitation_create(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("content:write")),
):
    """Mint a one-time invitation; the plaintext link is shown exactly once.

    Only ``sha256(token)`` is persisted (``create_invitation(token_hash=...)``);
    the full ``/admin/invite/{token}`` link rides the creation flash, which is
    the single time plaintext exists. The pending-invitations table shows a
    hash prefix only.
    """
    domain = workspaces.get_domain(db, domain_key=domain_key)
    if domain is None:
        raise HTTPException(status_code=404, detail=f"domain {domain_key!r} not found")
    form = await request.form()
    role = (form.get("role") or "").strip()
    back = _back_to_domain(domain_key)
    try:
        days = int((form.get("expires_days") or "").strip() or "7")
        if not 1 <= days <= 365:
            raise ValueError("expires_days must be between 1 and 365")
    except ValueError as exc:
        return _flash(back, "flash.invitation_failed", err=True, detail=str(exc))
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=days)
    try:
        workspaces.create_invitation(
            db, domain_id=domain["id"], role=role, invited_by=_operator_of(user),
            expires_at=expires_at, token_hash=token_hash,
        )
    except ValueError as exc:
        return _flash(back, "flash.invitation_failed", err=True, detail=str(exc))
    return _flash(
        back, "flash.invitation_created", detail=f"/admin/invite/{token}"
    )


# --------------------------------------------------------------- rag corpus #
# RAG corpus registry (change add-domain-rag-corpus-service, design D5).
# Per spec 域语料登记: 登记与管理 SHALL 走 admin 面（admin 平台 scope）+ 该域
# lead 合成执法 — the same two-gate composition as the publish route, with the
# platform gate raised to ``admin`` (the registry shapes the platform's
# retrieval surface). Admins bypass the domain check; a lead additionally needs
# the ``admin`` platform scope. The data layer is ``src/search/resolver.py``
# (kernel): it validates the index-name prefix, duplicates and source shapes —
# its ValueError message names every problem and rides the flash detail.


@write_router.post(
    "/admin/domains/{domain_key}/rag/register", include_in_schema=False,
    name="admin_domain_rag_register",
    dependencies=[
        Depends(require_scope("admin")),
        Depends(require_domain_role("lead")),
    ],
)
async def admin_domain_rag_register(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("admin")),
):
    """Register/replace the domain's RAG corpus (index name + MinIO sources).

    Form: ``index_name`` (must carry the ``{domain_key}-`` prefix per the
    kernel's cross-tenant guard), ``sources`` (JSON array of
    ``{"bucket": …, "prefix": …}``), ``embedding_model`` (optional declaration
    bit; empty = the global default). Re-registration upserts the row.
    """
    domain = workspaces.get_domain(db, domain_key=domain_key)
    if domain is None:
        raise HTTPException(status_code=404, detail=f"domain {domain_key!r} not found")
    form = await request.form()
    index_name = (form.get("index_name") or "").strip()
    embedding_model = (form.get("embedding_model") or "").strip() or None
    back = _back_to_domain(domain_key)
    try:
        sources = json.loads(form.get("sources") or "[]")
    except (json.JSONDecodeError, TypeError) as exc:
        return _flash(back, "flash.rag_sources_invalid", err=True, detail=str(exc))
    if not isinstance(sources, list):
        return _flash(back, "flash.rag_sources_invalid", err=True, detail="sources must be a JSON array")
    from src.search.resolver import register_corpus  # lazy: kernel import

    try:
        register_corpus(
            db,
            domain_key=domain_key,
            index_name=index_name,
            sources=sources,
            registered_by=_operator_of(user),
            embedding_model=embedding_model,
        )
    except ValueError as exc:
        return _flash(back, "flash.rag_register_failed", err=True, detail=str(exc))
    return _flash(back, "flash.rag_registered")


@write_router.post(
    "/admin/domains/{domain_key}/rag/ingest", include_in_schema=False,
    name="admin_domain_rag_ingest",
    dependencies=[
        Depends(require_scope("admin")),
        Depends(require_domain_role("lead")),
    ],
)
async def admin_domain_rag_ingest(
    request: Request,
    domain_key: str,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("admin")),
):
    """Fire-and-forget corpus ingest in a daemon thread (design D6 风险③).

    ``run_ingest`` pulls the domain's declared MinIO sources, chunks and embeds,
    then writes the domain's ES index — far too slow for a request thread on
    real corpora, so the route only validates the registration and hands the
    work to a daemon thread; the outcome (summary or failure) lands in the
    service log. The thread opens its own DB connection (the request-scoped one
    dies with the response); the CLI (``python -m src.search.ingest --domain
    …``) remains the batch channel.
    """
    domain = workspaces.get_domain(db, domain_key=domain_key)
    if domain is None:
        raise HTTPException(status_code=404, detail=f"domain {domain_key!r} not found")
    form = await request.form()
    prefix = (form.get("prefix") or "").strip() or None
    back = _back_to_domain(domain_key)
    from src.search.resolver import get_corpus  # lazy: kernel import

    if get_corpus(db, domain_key=domain_key) is None:
        # 未登记域如实 (spec 域语料登记): no corpus -> no ingest surface.
        return _flash(back, "flash.rag_ingest_failed", err=True, detail="该域未登记 RAG 语料")

    def _run() -> None:
        try:
            from src.search.ingest import run_ingest

            summary = run_ingest(domain_key, prefix=prefix)
            logger.info("rag ingest domain=%s outcome=%s", domain_key, summary)
        except Exception:  # noqa: BLE001 - background task: log, never raise
            logger.exception("rag ingest domain=%s failed", domain_key)

    threading.Thread(target=_run, name=f"rag-ingest-{domain_key}", daemon=True).start()
    return _flash(back, "flash.rag_ingest_started")


# ---------------------------------------------------------------- invitations #
# Viewing an invitation requires NO auth: the token in the URL is itself the
# capability (DB stores its digest only), and the invitee typically has no
# account yet. Accepting requires a session — a logged-out accepter is sent
# through the existing Logto login flow and returns via its ``next`` param.


@read_only_router.get(
    "/admin/invite/{token}", include_in_schema=False, name="admin_invite_view"
)
def admin_invite_view(request: Request, token: str, db: DbConn = Depends(get_db)):
    """Invitation landing page — anonymous-safe, neutral on any invalid state.

    Unknown digest, already-accepted, expired, or a vanished domain all render
    the same neutral "invitation invalid" state (200) — never a 500, and no
    data leak beyond what the token holder is entitled to see.
    """
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    session_user = _session_user(request) or {}
    context: dict[str, Any] = {
        "invalid": True,
        "invitation": None,
        "domain": None,
        "token": token,
        "signed_in_name": session_user.get("name") or session_user.get("email") or "",
    }
    invitation = workspaces.get_invitation(db, token_hash=token_hash)
    if invitation is not None:
        domain = workspaces.get_domain(db, domain_id=invitation["domain_id"])
        expired = _expired_for_display(invitation["expires_at"])
        used = invitation["accepted_at"] is not None
        context["invitation"] = invitation
        context["domain"] = domain
        context["invalid"] = used or expired or domain is None
    return _templates.TemplateResponse(request, "admin_invite_accept.html", context)


@write_router.api_route(
    "/admin/invite/{token}/accept", methods=["GET", "POST"],
    include_in_schema=False, name="admin_invite_accept",
)
async def admin_invite_accept(
    request: Request, token: str, db: DbConn = Depends(get_db)
):
    """Accept an invitation on behalf of the signed-in session identity.

    GET on this URL (what the login round-trip produces when ``next`` carried
    the POST path) just bounces back to the view page. POST without a session
    redirects into ``/auth/login`` with ``next`` pointing back at the invite
    view, so the invitee completes the existing OIDC flow and accepts after.
    """
    if request.method == "GET":
        return RedirectResponse(url=f"/admin/invite/{quote(token)}", status_code=303)
    session_user = _session_user(request) or {}
    sub = str(session_user.get("sub") or "")
    if not sub:
        # Not signed in: walk the existing login flow, then come back to the
        # invitation page (never bind an anonymous identity to a domain).
        return RedirectResponse(
            url=f"/auth/login?next={quote('/admin/invite/' + token)}", status_code=302
        )
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    back = f"/admin/invite/{quote(token)}"
    try:
        workspaces.accept_invitation(db, token_hash=token_hash, user_id=sub)
    except (workspaces.InvitationError, ValueError) as exc:
        # Unknown / used / expired token -> back to the page, which renders the
        # neutral invalid state; the message names why (fail closed, no 500).
        return _flash(back, "flash.invite_failed", err=True, detail=str(exc))
    return _flash("/", "flash.invite_accepted")


# ------------------------------------------------------------------ libraries #


def _split_lines(raw: str) -> list[str]:
    return [x.strip() for x in (raw or "").splitlines() if x.strip()]


@read_only_router.get(
    "/admin/libraries", include_in_schema=False, name="admin_libraries",
    dependencies=[Depends(require_scope("admin"))],
)
def admin_libraries(request: Request, db: DbConn = Depends(get_db)):
    """The library registry: what corpora exist, and how to add one.

    A domain only chooses what to *subscribe*; libraries are platform-level, so
    this page lives beside the other admin gates. Creating one is the step that
    used to require running a script inside a pod.
    """
    from ...bench import libraries as library_store

    return _templates.TemplateResponse(
        request,
        "admin_libraries.html",
        {
            "libraries": library_store.list_libraries(db),
            "sources": {
                lib["library_key"]: library_store.list_sources(db, library_id=lib["id"])
                for lib in library_store.list_libraries(db)
            },
            "backends": library_store.BACKENDS,
            "external": library_store.EXTERNAL_BACKENDS,
            "domains": workspaces.list_domains(db),
        },
    )


@write_router.post(
    "/admin/libraries", include_in_schema=False, name="admin_library_create",
    dependencies=[Depends(require_scope("admin"))],
)
async def admin_library_create(
    request: Request,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("admin")),
):
    from ...bench import libraries as library_store

    form = await request.form()
    backend = (form.get("backend") or "").strip()
    location: dict = {}
    try:
        # External libraries are addressed by env *names*. The form deliberately
        # has no field for a DSN or a key: this page is rendered, dumped and
        # reviewed, so a secret entered here would leak three ways.
        if backend == "qdrant":
            location = {
                "url_env": (form.get("url_env") or "").strip(),
                "collection": (form.get("collection") or "").strip(),
            }
        elif backend == "pgvector-external":
            location = {"dsn_env": (form.get("dsn_env") or "").strip()}
        dims = int((form.get("dims") or "0").strip() or 0)
        library_store.create_library(
            db,
            library_key=(form.get("library_key") or "").strip(),
            name=(form.get("name") or "").strip(),
            backend=backend,
            embedding_model=(form.get("embedding_model") or "").strip() or None,
            dims=dims,
            location=location or None,
            created_by=_operator_of(user),
        )
    except (ValueError, TypeError) as exc:
        return _flash("/admin/libraries", "flash.library_create_failed", err=True, detail=str(exc))
    return _flash("/admin/libraries", "flash.library_created")


@write_router.post(
    "/admin/libraries/{library_key}/sources", include_in_schema=False,
    name="admin_library_source_add",
    dependencies=[Depends(require_scope("admin"))],
)
async def admin_library_source_add(
    library_key: str,
    request: Request,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("admin")),
):
    """Register one source. ``match`` is the filter that defines it, for external
    libraries: a source is not a prefix there, it is a predicate."""
    from ...bench import libraries as library_store

    form = await request.form()
    rule: dict = {}
    raw_match = (form.get("match") or "").strip()
    if raw_match:
        try:
            match = json.loads(raw_match)
        except json.JSONDecodeError as exc:
            return _flash("/admin/libraries", "flash.library_source_failed",
                          err=True, detail=f"match must be JSON: {exc}")
        if not isinstance(match, dict):
            return _flash("/admin/libraries", "flash.library_source_failed",
                          err=True, detail="match must be a JSON object")
        rule = {"match": match}
    try:
        library_store.add_source(
            db,
            library_key=library_key,
            source_key=(form.get("source_key") or "").strip(),
            uri=(form.get("uri") or "").strip(),
            source_kind=(form.get("source_kind") or "object-prefix").strip(),
            ingest_rule=rule,
            created_by=_operator_of(user),
        )
    except ValueError as exc:
        return _flash("/admin/libraries", "flash.library_source_failed", err=True, detail=str(exc))
    return _flash("/admin/libraries", "flash.library_source_added")


@write_router.post(
    "/admin/libraries/{library_key}/subscribe", include_in_schema=False,
    name="admin_library_subscribe",
    dependencies=[Depends(require_scope("admin"))],
)
async def admin_library_subscribe(
    library_key: str,
    request: Request,
    db: DbConn = Depends(get_db),
    user: User = Depends(require_scope("admin")),
):
    """Grant a domain a library. ``sources`` left empty means "every source"."""
    from ...bench import libraries as library_store

    form = await request.form()
    domain_key = (form.get("domain_key") or "").strip()
    selected = [s for s in (form.get("sources") or "").split(",") if s.strip()]
    domain = workspaces.get_domain(db, domain_key=domain_key)
    if domain is None:
        return _flash("/admin/libraries", "flash.library_subscribe_failed",
                      err=True, detail=f"unknown domain {domain_key!r}")
    try:
        library_store.subscribe(
            db,
            domain_id=domain["id"],
            library_key=library_key,
            source_filter=selected or None,
            created_by=_operator_of(user),
        )
    except ValueError as exc:
        return _flash("/admin/libraries", "flash.library_subscribe_failed",
                      err=True, detail=str(exc))
    return _flash("/admin/libraries", "flash.library_subscribed")


router = APIRouter(tags=["admin"])
router.include_router(read_only_router)
router.include_router(write_router)
