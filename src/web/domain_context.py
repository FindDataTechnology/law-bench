"""Domain context for the domain-first console (change ``add-domain-first-workbench``).

One place that answers "which domain am I in, what may I do here, and what do I
call this in the chrome" so the six console areas never re-derive it. The route
gates stay authoritative (``require_scope`` then ``require_domain_role``); this
module is composition **for rendering** plus the one navigation write
(``touch_last_opened``).

Role vocabulary is the workspace kernel's, not an invented one: ``annotator``
(审核标注员) < ``expert`` (领域专家) < ``lead`` (领域负责人), with a platform
``admin`` bypassing the domain check (four levels including platform admin, per
``domain-workspace`` 四级领域角色).
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .auth.deps import User
from ..bench import workspaces

#: The console's fixed areas, in navigation order. ``id`` doubles as the URL
#: segment and the i18n key suffix; ``min_role`` is the weakest domain role that
#: may see the area at all (finer action gates live inside each area).
AREAS: tuple[dict, ...] = (
    {"id": "overview", "min_role": "annotator"},
    {"id": "ontology", "min_role": "annotator"},
    # The corpus a domain may actually retrieve from, with its inheritance
    # explanation. Read-only for annotators; subscriptions are lead-gated.
    {"id": "knowledge", "min_role": "annotator"},
    # The same corpus seen as documents instead of chunks: browse what the
    # library holds and take a document (or its articles) into the ontology.
    {"id": "library", "min_role": "annotator"},
    # Evaluation standards: own rubrics plus the ones inherited by reference.
    {"id": "eval-standards", "min_role": "annotator"},
    # Formerly ``bench``: the shelf of assigned assets plus run history. The old
    # URL is kept as a 302 so no bookmark or legacy link breaks.
    {"id": "eval-runs", "min_role": "annotator"},
    {"id": "inbox", "min_role": "annotator"},
    # 值班长视图：台账 + 质量比 + 按批待确认。只读页，确认动作仍走 inbox 的
    # lead 闸（页面上出现的按钮只是入口，权限不由页面决定）。
    {"id": "team", "min_role": "annotator"},
    {"id": "publish", "min_role": "annotator"},
    {"id": "settings", "min_role": "lead"},
)


def is_platform_admin(user: User) -> bool:
    """``admin``/``*`` scope — the only bypass of the domain role check."""
    scopes = user.scopes or []
    return "*" in scopes or "admin" in scopes


def capability(
    conn: Any, domain: dict, user: User
) -> dict:
    """What the signed-in identity may do in ``domain`` — chrome only.

    ``role`` is the active workspace role, or ``"admin"`` for a platform admin
    without a membership row (the same convention ``authoring._capability``
    uses). Returning ``can_*`` flags rather than raw ranks keeps the templates
    readable and makes the "role table changed" edit a one-line change here.
    """
    admin = is_platform_admin(user)
    role = workspaces.get_active_role(conn, domain_id=domain["id"], user_id=user.sub)
    if not role and admin:
        role = "admin"
    effective = role or ""
    rank = workspaces.ROLE_RANK.get(effective, -1)
    if admin:
        rank = max(rank, workspaces.ROLE_RANK["lead"])
    return {
        "role": effective,
        "is_platform_admin": admin,
        "can_read": rank >= workspaces.ROLE_RANK["annotator"],
        "can_write": rank >= workspaces.ROLE_RANK["expert"],
        "can_assign": rank >= workspaces.ROLE_RANK["lead"],
        "can_confirm": rank >= workspaces.ROLE_RANK["lead"],
        "can_publish": rank >= workspaces.ROLE_RANK["lead"],
        "can_catalog": rank >= workspaces.ROLE_RANK["lead"],
        "can_manage_members": rank >= workspaces.ROLE_RANK["lead"],
    }


def visible_areas(cap: dict) -> list[dict]:
    """The areas this capability may see, in navigation order."""
    rank_of = workspaces.ROLE_RANK
    role_rank = rank_of.get(cap.get("role") or "", -1)
    if cap.get("is_platform_admin"):
        role_rank = max(role_rank, rank_of["lead"])
    return [a for a in AREAS if role_rank >= rank_of[a["min_role"]]]


def resolve_domain(conn: Any, domain_key: str) -> dict:
    """Resolve the path domain or 404.

    ``require_domain_role`` already 403'd every non-member (fail-closed), so a
    miss here is only reachable for a platform admin typo — an honest 404 leaks
    nothing.
    """
    domain = workspaces.get_domain(conn, domain_key=domain_key)
    if domain is None:
        raise HTTPException(status_code=404, detail=f"domain {domain_key!r} not found")
    return domain


def console_context(
    conn: Any, domain: dict, user: User, *, touch: bool = False
) -> dict:
    """The chrome context every domain area page needs.

    ``touch`` stamps this user's recency marker for the domain list order; it is
    applied only on the landing areas (overview) so writing a page view never
    happens on a pure read of a deep area.
    """
    if touch:
        workspaces.touch_last_opened(conn, domain_id=domain["id"], user_id=user.sub)
        conn.commit()
    cap = capability(conn, domain, user)
    return {
        "domain": domain,
        "cap": cap,
        "areas": visible_areas(cap),
        # The switcher lists exactly the domains this identity may enter; it is
        # never derived from a client-supplied value.
        "switcher_domains": workspaces.list_member_domains(conn, user_id=user.sub),
    }


def member_domain_count(conn: Any, user_id: str) -> int:
    """How many domains this identity may enter (drives the landing decision)."""
    return len(workspaces.list_member_domains(conn, user_id=user_id))
