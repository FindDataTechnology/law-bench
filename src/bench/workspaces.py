"""Domain lifecycle, membership history, and invitation acceptance.

A domain is a workspace instantiated from one exact template row: the record
anchors both ``template_id`` and ``template_version`` so later template edits
never retroactively change it. Membership is append-only history (a role
change retires the active row and inserts a new one) and invitations carry
only a credential digest, never a plaintext value.

All public functions borrow a DB-API connection supplied by the caller; this
module never opens or closes one. Writes are committed once, at the end of the
operation -- ``accept_invitation`` deliberately performs its UPDATE and its
membership insert before a single commit so the two cannot diverge.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from . import templates

ROLES = ("annotator", "expert", "lead")  # ascending rank
ROLE_RANK = {"annotator": 0, "expert": 1, "lead": 2}


class InvitationError(ValueError):
    """An invitation token cannot be accepted (unknown, used, or expired)."""


_DOMAIN_SELECT = (
    "SELECT d.id, d.key, d.name, d.template_id, d.template_version, "
    "t.name AS template_name, d.created_by, d.created_at, d.path, d.archived_at "
    "FROM domains d JOIN ontology_templates t ON t.id = d.template_id"
)
_DOMAIN_KEYS = (
    "id",
    "key",
    "name",
    "template_id",
    "template_version",
    "template_name",
    "path",
    "created_by",
    "created_at",
    "archived_at",
)
_DOMAIN_INSERT_KEYS = (
    "id",
    "key",
    "name",
    "template_id",
    "template_version",
    "created_by",
    "created_at",
)

_MEMBER_COLS = "id, domain_id, user_id, role, added_by, added_at, removed_at"
_MEMBER_KEYS = (
    "id",
    "domain_id",
    "user_id",
    "role",
    "added_by",
    "added_at",
    "removed_at",
)

_INVITATION_COLS = (
    "id, domain_id, role, token_hash, invited_by, expires_at, "
    "created_at, accepted_at, accepted_by"
)
_INVITATION_KEYS = (
    "id",
    "domain_id",
    "role",
    "token_hash",
    "invited_by",
    "expires_at",
    "created_at",
    "accepted_at",
    "accepted_by",
)


def _iso(val: Any) -> Any:
    """Return a consistent ISO-8601 string for driver timestamps; pass text through."""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return val


def _scalar(row: Any) -> Any:
    """First value of a single-column row, dict-row or tuple."""
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


def _row_to_dict(row: Any, keys: tuple[str, ...]) -> dict:
    if isinstance(row, dict):
        values = [row[k] for k in keys]
    else:
        values = list(row)
    return {k: _iso(v) for k, v in zip(keys, values)}


def _validate_role(role: str) -> None:
    if role not in ROLE_RANK:
        raise ValueError(f"role must be one of {list(ROLES)}")


# ------------------------------------------------------------------ domains


def instantiate_domain(
    conn: Any,
    *,
    key: str,
    name: str,
    template_name: str,
    template_version: Optional[int],
    created_by: str,
    parent_key: Optional[str] = None,
) -> dict:
    """Create a workspace anchored to one concrete template version.

    Refuses a missing template or a structurally incomplete template schema
    (the missing/invalid items are named in the error), and refuses a duplicate
    domain key.

    ``parent_key`` places the domain in the tree: the materialized path becomes
    ``<parent path>/<key>``. Without it the domain is a root whose path is its
    own key. A missing parent is refused rather than silently creating a root —
    a typo must not detach a sub-domain from its industry parent.
    """
    if not key or not name:
        raise ValueError("key and name are required")
    tmpl = templates.get_template(
        conn, name=template_name, version=template_version
    )
    if tmpl is None:
        if template_version is None:
            raise ValueError(f"template {template_name!r} not found")
        raise ValueError(
            f"template {template_name!r} version {template_version} not found"
        )
    problems = templates.validate_template_schema(tmpl["schema"])
    if problems:
        raise ValueError("template schema is invalid: " + "; ".join(problems))

    # Draft domains are allowed: a domain may exist before its template has
    # rulers, and the estate matrix reports it as `quality:template` until they
    # arrive. The refusal belongs to *using* a template's rulers, so instantiation
    # only refuses one whose rulers were declared and cannot be resolved — that is
    # a broken promise, not a template still being built.
    from . import template_readiness

    declared_rulers = template_readiness.rubric_refs(tmpl["schema"])
    if declared_rulers:
        readiness = template_readiness.readiness(
            conn, domain_path=parent_key or key, schema=tmpl["schema"]
        )
        if readiness["missing"]:
            raise ValueError(
                "template declares rulers that cannot be resolved in this scope: "
                + "、".join(readiness["missing"])
            )

    existing = conn.execute(
        "SELECT archived_at FROM domains WHERE key = %s LIMIT 1", (key,)
    ).fetchone()
    if existing:
        # An archived key is still taken: history (proposals, runs, events) refers
        # to a key that must keep meaning the same domain forever. Reusing it
        # would splice two generations of a line into one record.
        if existing["archived_at"] is not None:
            raise ValueError(
                f"domain key {key!r} belongs to an archived domain — restore it, "
                "or choose a different key"
            )
        raise ValueError(f"domain key {key!r} already exists")

    # Materialized path: a root's path is its key; a sub-domain composes
    # ``<parent path>/<key>``. Computed here (not by a trigger) so the same rule
    # holds for the admin form and the console wizard.
    parent = None
    if parent_key:
        parent = get_domain(conn, domain_key=parent_key)
        if parent is None:
            raise ValueError(f"parent domain {parent_key!r} not found")
    path = f"{parent['path']}/{key}" if parent else key
    cur = conn.execute(
        """
        INSERT INTO domains (key, name, template_id, template_version, created_by, path)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id, key, name, template_id, template_version, created_by,
                  created_at, path, archived_at
        """,
        (key, name, tmpl["id"], tmpl["version"], created_by, path),
    )
    inserted = _row_to_dict(cur.fetchone(), _DOMAIN_INSERT_KEYS + ("path",))
    conn.commit()
    return {
        "id": inserted["id"],
        "key": inserted["key"],
        "name": inserted["name"],
        "template_id": inserted["template_id"],
        "template_version": inserted["template_version"],
        "template_name": tmpl["name"],
        "path": inserted["path"],
        "created_by": inserted["created_by"],
        "created_at": inserted["created_at"],
    }


def get_domain(
    conn: Any,
    *,
    domain_key: Optional[str] = None,
    domain_id: Optional[int] = None,
) -> Optional[dict]:
    """Look up a domain by key or id; ``None`` when no selector is given."""
    if domain_key is not None:
        cur = conn.execute(_DOMAIN_SELECT + " WHERE d.key = %s", (domain_key,))
    elif domain_id is not None:
        cur = conn.execute(_DOMAIN_SELECT + " WHERE d.id = %s", (domain_id,))
    else:
        return None
    row = cur.fetchone()
    return _row_to_dict(row, _DOMAIN_KEYS) if row else None


def list_domains(
    conn: Any, *, user_id: Optional[str] = None, include_archived: bool = False
) -> list[dict]:
    """All domains, or only those where ``user_id`` has an active membership.

    Archived domains are excluded by default. This is the single filter point for
    the estate, the switcher and the gap matrix — filtering at each call site
    would drift into several definitions of "a domain".
    """
    where, params = [], []
    if not include_archived:
        where.append("d.archived_at IS NULL")
    if user_id is not None:
        where.append(
            "EXISTS (SELECT 1 FROM domain_members m "
            "WHERE m.domain_id = d.id AND m.user_id = %s AND m.removed_at IS NULL)"
        )
        params.append(user_id)
    sql = _DOMAIN_SELECT + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY d.id"
    cur = conn.execute(sql, tuple(params))
    return [_row_to_dict(r, _DOMAIN_KEYS) for r in cur.fetchall()]


def archive_domain(conn: Any, *, domain_key: str, actor: str) -> dict:
    """Soft-exit a domain: hide it from the estate, keep everything it holds.

    Only ``archived_at`` is written. Idempotent — archiving twice keeps the first
    timestamp, because "when did this line stop" should not move.
    """
    domain = get_domain(conn, domain_key=domain_key)
    if domain is None:
        raise ValueError(f"domain {domain_key!r} not found")
    if domain.get("archived_at") is not None:
        return domain
    conn.execute(
        "UPDATE domains SET archived_at = now() WHERE id = %s", (domain["id"],)
    )
    conn.commit()
    return get_domain(conn, domain_key=domain_key)


def restore_domain(conn: Any, *, domain_key: str, actor: str) -> dict:
    """Undo an archive: clear the timestamp, nothing else."""
    domain = get_domain(conn, domain_key=domain_key)
    if domain is None:
        raise ValueError(f"domain {domain_key!r} not found")
    conn.execute("UPDATE domains SET archived_at = NULL WHERE id = %s", (domain["id"],))
    conn.commit()
    return get_domain(conn, domain_key=domain_key)


# ---------------------------------------------------------------- membership


def list_members(conn: Any, *, domain_id: int) -> list[dict]:
    """Active membership rows only (retired rows stay as history)."""
    cur = conn.execute(
        f"SELECT {_MEMBER_COLS} FROM domain_members "
        "WHERE domain_id = %s AND removed_at IS NULL ORDER BY added_at, id",
        (domain_id,),
    )
    return [_row_to_dict(r, _MEMBER_KEYS) for r in cur.fetchall()]


def get_active_role(conn: Any, *, domain_id: int, user_id: str) -> Optional[str]:
    """The user's role in the domain, or ``None`` without an active membership."""
    row = conn.execute(
        "SELECT role FROM domain_members "
        "WHERE domain_id = %s AND user_id = %s AND removed_at IS NULL",
        (domain_id, user_id),
    ).fetchone()
    return _scalar(row)


def list_invitations(conn: Any, *, domain_id: int, limit: int = 50) -> list[dict]:
    """Invitations issued for one domain, newest first.

    Carries only what a settings page may show: id, role, issuer, timestamps.
    ``token_hash`` is deliberately NOT selected — the plaintext token exists
    solely at creation time (the accept link), and a stored digest has no
    display value.
    """
    cur = conn.execute(
        "SELECT id, role, invited_by, expires_at, created_at, accepted_at, "
        "accepted_by FROM domain_invitations "
        "WHERE domain_id = %s ORDER BY created_at DESC, id DESC LIMIT %s",
        (domain_id, int(limit)),
    )
    return [
        _row_to_dict(
            r,
            (
                "id",
                "role",
                "invited_by",
                "expires_at",
                "created_at",
                "accepted_at",
                "accepted_by",
            ),
        )
        for r in cur.fetchall()
    ]


def list_member_domains(conn: Any, *, user_id: str) -> list[dict]:
    """Domains the user may enter, with their role, most recently opened first.

    Backs the C5 domain-first landing (``/d``): one row per active membership,
    carrying the domain record plus ``role`` and ``last_opened_at``. Ordering is
    "my own recency first, then never-opened domains by id" so the list is
    stable for a brand-new identity. ``last_opened_at`` is a per-user navigation
    hint (see ``WORKSPACE_SCHEMA``), never content.
    """
    # Archived domains are not listed here either: a retired line must not keep
    # appearing on the landing page just because its members still exist.
    cur = conn.execute(
        "SELECT d.id, d.key, d.name, d.template_id, d.template_version, "
        "t.name AS template_name, d.created_by, d.created_at, d.path, d.archived_at, "
        "m.role, m.last_opened_at "
        "FROM domains d JOIN ontology_templates t ON t.id = d.template_id "
        "JOIN domain_members m ON m.domain_id = d.id "
        "WHERE m.user_id = %s AND m.removed_at IS NULL AND d.archived_at IS NULL "
        "ORDER BY m.last_opened_at DESC NULLS LAST, d.id",
        (user_id,),
    )
    return [
        _row_to_dict(r, _DOMAIN_KEYS + ("path", "role", "last_opened_at"))
        for r in cur.fetchall()
    ]


def touch_last_opened(conn: Any, *, domain_id: int, user_id: str) -> None:
    """Stamp the user's own recency marker for this domain (no commit).

    Only an ACTIVE membership is touched — a retired row is history and must
    stay byte-identical. No row matched (e.g. a platform admin browsing without
    a membership) is a silent no-op: the console never invents a membership.
    """
    conn.execute(
        "UPDATE domain_members SET last_opened_at = now() "
        "WHERE domain_id = %s AND user_id = %s AND removed_at IS NULL",
        (domain_id, user_id),
    )


def _deactivate_active_membership(conn: Any, *, domain_id: int, user_id: str) -> None:
    """Retire the active row (no commit -- caller owns the transaction)."""
    conn.execute(
        "UPDATE domain_members SET removed_at = now() "
        "WHERE domain_id = %s AND user_id = %s AND removed_at IS NULL",
        (domain_id, user_id),
    )


def _insert_member_row(
    conn: Any, *, domain_id: int, user_id: str, role: str, added_by: str
) -> dict:
    """Insert one active row (no commit -- caller owns the transaction)."""
    cur = conn.execute(
        f"INSERT INTO domain_members (domain_id, user_id, role, added_by) "
        f"VALUES (%s, %s, %s, %s) RETURNING {_MEMBER_COLS}",
        (domain_id, user_id, role, added_by),
    )
    return _row_to_dict(cur.fetchone(), _MEMBER_KEYS)


def add_member(
    conn: Any, *, domain_id: int, user_id: str, role: str, added_by: str
) -> dict:
    """Add/replace a membership append-only: retire the active row, then insert."""
    _validate_role(role)
    if not user_id:
        raise ValueError("user_id is required")
    _deactivate_active_membership(conn, domain_id=domain_id, user_id=user_id)
    member = _insert_member_row(
        conn, domain_id=domain_id, user_id=user_id, role=role, added_by=added_by
    )
    conn.commit()
    return member


def change_member_role(
    conn: Any, *, domain_id: int, user_id: str, role: str, changed_by: str
) -> dict:
    """Append-only role change; the new row records ``added_by=changed_by``."""
    return add_member(
        conn,
        domain_id=domain_id,
        user_id=user_id,
        role=role,
        added_by=changed_by,
    )


def remove_member(
    conn: Any, *, domain_id: int, user_id: str, removed_by: str
) -> None:
    """Retire the active row without deleting it (history is preserved).

    ``removed_by`` is accepted for API symmetry; the table has no operator
    column for a retirement, so the original row (with its ``added_by``) is
    kept intact and only ``removed_at`` is set.
    """
    conn.execute(
        "UPDATE domain_members SET removed_at = now() "
        "WHERE domain_id = %s AND user_id = %s AND removed_at IS NULL",
        (domain_id, user_id),
    )
    conn.commit()


# --------------------------------------------------------------- invitations


def create_invitation(
    conn: Any,
    *,
    domain_id: int,
    role: str,
    invited_by: str,
    expires_at: Any,
    token_hash: str,
) -> dict:
    """Store an invitation by credential digest only (never a plaintext token)."""
    _validate_role(role)
    if not token_hash:
        raise ValueError("token_hash is required")
    cur = conn.execute(
        f"INSERT INTO domain_invitations "
        f"(domain_id, role, token_hash, invited_by, expires_at) "
        f"VALUES (%s, %s, %s, %s, %s) RETURNING {_INVITATION_COLS}",
        (domain_id, role, token_hash, invited_by, expires_at),
    )
    row = cur.fetchone()
    conn.commit()
    return _row_to_dict(row, _INVITATION_KEYS)


def get_invitation(conn: Any, *, token_hash: str) -> Optional[dict]:
    """Fetch an invitation by its digest."""
    cur = conn.execute(
        f"SELECT {_INVITATION_COLS} FROM domain_invitations "
        "WHERE token_hash = %s",
        (token_hash,),
    )
    row = cur.fetchone()
    return _row_to_dict(row, _INVITATION_KEYS) if row else None


def _python_expired(value: Any) -> bool:
    """Fallback expiry comparison for non-SQL test doubles; fail closed."""
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


def _is_expired(conn: Any, *, token_hash: str, expires_at: Any) -> bool:
    """Compare against the database clock; fall back to Python for test doubles."""
    row = conn.execute(
        "SELECT (expires_at < now()) AS expired FROM domain_invitations "
        "WHERE token_hash = %s",
        (token_hash,),
    ).fetchone()
    if row is not None:
        return bool(_scalar(row))
    return _python_expired(expires_at)


def accept_invitation(conn: Any, *, token_hash: str, user_id: str) -> dict:
    """Accept a token: mark it used and create the membership atomically.

    Raises :class:`InvitationError` for an unknown digest, an already-accepted
    token, or an expired token (the message names which). The UPDATE and the
    membership insert share one transaction with exactly one commit, so a
    token can never be consumed without the matching membership -- and is
    unusable afterwards. Returns the updated invitation row.
    """
    if not user_id:
        raise ValueError("user_id is required")
    invitation = get_invitation(conn, token_hash=token_hash)
    if invitation is None:
        raise InvitationError("unknown invitation token")
    if invitation["accepted_at"] is not None:
        raise InvitationError("invitation already accepted")
    if _is_expired(
        conn, token_hash=token_hash, expires_at=invitation["expires_at"]
    ):
        raise InvitationError("invitation expired")

    cur = conn.execute(
        f"UPDATE domain_invitations SET accepted_at = now(), accepted_by = %s "
        f"WHERE token_hash = %s AND accepted_at IS NULL "
        f"RETURNING {_INVITATION_COLS}",
        (user_id, token_hash),
    )
    updated = cur.fetchone()
    if updated is None:
        raise InvitationError("invitation already accepted")

    _deactivate_active_membership(
        conn, domain_id=invitation["domain_id"], user_id=user_id
    )
    _insert_member_row(
        conn,
        domain_id=invitation["domain_id"],
        user_id=user_id,
        role=invitation["role"],
        added_by=user_id,
    )
    conn.commit()
    return _row_to_dict(updated, _INVITATION_KEYS)
