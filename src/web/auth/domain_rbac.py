"""Domain-scoped RBAC dependency factory.

Composes the existing platform-scope enforcement with a per-domain role check.
The factory intentionally does NOT take a platform scope: callers compose the
two gates in order, e.g.::

    dependencies=[
        Depends(require_scope("content:write")),
        Depends(require_domain_role("expert")),
    ]

Platform roles remain Logto-only (``require_scope`` is unchanged); the domain
role's sole source of truth is the workspace membership record. A platform
``admin`` (or the ``"*"`` wildcard) bypasses the domain check entirely. Every
other denial is reported as ``无该域权限`` -- a missing/unknown domain is NOT
disguised as a 404, because revealing existence to a non-member would leak
cross-tenant information.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Request

from src.bench import workspaces
from src.web.deps import get_db

from .deps import User, get_current_user

_NO_PERMISSION_DETAIL = "无该域权限"


def require_domain_role(min_role: str = "annotator"):
    """Return a FastAPI dependency enforcing a minimum domain role.

    Reads ``domain_key`` from ``request.path_params``. Admin/wildcard scopes
    pass unconditionally; otherwise the caller must hold an active membership
    whose rank is at least ``min_role`` (``annotator`` < ``expert`` < ``lead``).
    Missing membership, too-low rank, or an unknown domain all fail closed with
    HTTP 403 and detail ``无该域权限``. A 400 is raised only when the path
    genuinely has no ``domain_key`` parameter. Returns the resolved ``User``.
    """
    required_rank = workspaces.ROLE_RANK.get(min_role)
    if required_rank is None:
        raise ValueError(
            f"unknown min_role {min_role!r}; expected one of "
            f"{list(workspaces.ROLES)}"
        )

    def _checker(
        request: Request,
        user: User = Depends(get_current_user),
        conn: Any = Depends(get_db),
    ) -> User:
        scopes = user.scopes or []
        if "*" in scopes or "admin" in scopes:
            return user

        domain_key = request.path_params.get("domain_key")
        if not domain_key:
            raise HTTPException(
                status_code=400, detail="missing domain_key path param"
            )

        domain = workspaces.get_domain(conn, domain_key=str(domain_key))
        if domain is None:
            raise HTTPException(status_code=403, detail=_NO_PERMISSION_DETAIL)

        role = workspaces.get_active_role(
            conn, domain_id=domain["id"], user_id=user.sub
        )
        if role is None or workspaces.ROLE_RANK.get(role, -1) < required_rank:
            raise HTTPException(status_code=403, detail=_NO_PERMISSION_DETAIL)
        return user

    return _checker
