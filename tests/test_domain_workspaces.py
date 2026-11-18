"""Domain workspace store (add-ontology-template-and-workspaces, task 4.2).

Covers the workspace behaviors:
- instantiate_domain binds one exact template row/version, refuses duplicate
  keys, missing templates and structurally incomplete template schemas —
  including the DB-level gate against a row inserted directly via SQL
  (spec: 缺词表模板拒绝实例化 — 报明缺失项，不产生域);
- instantiation is a pure data operation: the domain shows up in
  list_domains() (spec: 实例化开域且内核零改动 — the no-kernel-file-change
  half is a CI-level gate, not assertable from a test);
- membership is append-only history with operator/role/time audit
  (spec: 成员管理留痕): a role change retires the old row (removed_at set,
  old role kept) and inserts one active row added_by=changed_by;
- get_active_role returns None for a removed member;
- list_domains(user_id=...) is permission-aware (active membership only);
- invitation lifecycle: get by hash, accept creates membership in the invited
  role atomically and marks accepted_at/accepted_by, second accept (same or
  different user) refused, unknown hash refused, expired token refused with no
  membership created (spec: 邀请制成员准入).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.bench import templates, workspaces
from src.bench.tiers import TIERS
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.workspaces import InvitationError
from src.eval.store import ensure_schema


@pytest.fixture()
def db_conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    # Inject the fixture's own connection so DDL lands on the per-test DB
    # instead of the process-wide cached shared connection (which stays bound
    # to whichever test DB connected first).
    ensure_schema(db_path=empty_db)
    yield empty_db


def valid_schema() -> dict:
    return {
        "entity_types": ["clause", "party"],
        "concept_structures": {"lifecycle": {"members": ["draft", "sign"]}},
        "relationship_kinds": ["references"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {"source_types": ["uploaded"]},
    }


def make_template(conn, name: str, *, versions: int = 1) -> dict:
    """Create a valid template with ``versions`` appended versions; return latest."""
    tmpl = templates.create_template(
        conn, name=name, schema=valid_schema(), created_by="admin-1"
    )
    for i in range(2, versions + 1):
        tmpl = templates.update_template(
            conn,
            name=name,
            schema={**valid_schema(), "entity_types": [f"entity-v{i}"]},
            created_by="admin-1",
        )
    return tmpl


def make_domain(conn, key: str = "dom-1", *, template_versions: int = 1) -> dict:
    tmpl = make_template(conn, f"tpl-{key}", versions=template_versions)
    return workspaces.instantiate_domain(
        conn,
        key=key,
        name=f"Domain {key}",
        template_name=f"tpl-{key}",
        template_version=tmpl["version"],
        created_by="admin-1",
    )


def _count(conn, table: str, where: str = "", params: tuple = ()) -> int:
    row = conn.execute(f"SELECT COUNT(*) AS n FROM {table} {where}", params).fetchone()
    return row["n"]


# ------------------------------------------------------------- instantiate


def test_instantiate_domain_binds_exact_template_row_and_version(db_conn):
    # template reaches v2 BEFORE instantiation; the domain anchors that exact row
    tmpl = make_template(db_conn, "bind-tpl", versions=2)

    domain = workspaces.instantiate_domain(
        db_conn,
        key="dom-bind",
        name="Bound Domain",
        template_name="bind-tpl",
        template_version=2,
        created_by="admin-1",
    )
    assert domain["key"] == "dom-bind"
    assert domain["name"] == "Bound Domain"
    assert domain["template_id"] == tmpl["id"]  # exact template ROW, not just name
    assert domain["template_version"] == 2
    assert domain["template_name"] == "bind-tpl"
    assert domain["created_by"] == "admin-1"
    assert domain["created_at"]

    fetched = workspaces.get_domain(db_conn, domain_key="dom-bind")
    assert fetched["id"] == domain["id"]
    assert fetched["template_id"] == tmpl["id"]
    assert fetched["template_version"] == 2

    # get_domain by id agrees
    by_id = workspaces.get_domain(db_conn, domain_id=domain["id"])
    assert by_id["key"] == "dom-bind"
    assert workspaces.get_domain(db_conn, domain_key="no-such") is None


def test_instantiate_domain_without_version_anchors_latest(db_conn):
    make_template(db_conn, "latest-tpl", versions=3)
    domain = workspaces.instantiate_domain(
        db_conn,
        key="dom-latest",
        name="Latest Domain",
        template_name="latest-tpl",
        template_version=None,
        created_by="admin-1",
    )
    assert domain["template_version"] == 3


def test_instantiate_domain_duplicate_key_raises_and_no_second_row(db_conn):
    make_domain(db_conn, "dom-dup")
    with pytest.raises(ValueError, match="already exists"):
        workspaces.instantiate_domain(
            db_conn,
            key="dom-dup",
            name="Second Attempt",
            template_name="tpl-dom-dup",
            template_version=None,
            created_by="admin-1",
        )
    assert _count(db_conn, "domains", "WHERE key = %s", ("dom-dup",)) == 1
    row = workspaces.get_domain(db_conn, domain_key="dom-dup")
    assert row["name"] == "Domain dom-dup"  # first one untouched


def test_instantiate_domain_missing_template_raises_and_no_domain(db_conn):
    with pytest.raises(ValueError, match="not found"):
        workspaces.instantiate_domain(
            db_conn,
            key="dom-ghost",
            name="Ghost Domain",
            template_name="no-such-template",
            template_version=None,
            created_by="admin-1",
        )
    # a named version that doesn't exist is also refused
    make_template(db_conn, "exists-tpl")
    with pytest.raises(ValueError, match="version 7 not found"):
        workspaces.instantiate_domain(
            db_conn,
            key="dom-ghost2",
            name="Ghost Domain 2",
            template_name="exists-tpl",
            template_version=7,
            created_by="admin-1",
        )
    assert _count(db_conn, "domains") == 0


def test_instantiate_rejects_schema_missing_vocabulary_inserted_directly(db_conn):
    """DB-level gate: a template row that bypassed create_template validation
    (inserted via raw SQL with a schema lacking tier_vocabulary) must still be
    refused at instantiation, naming the missing item, and produce no domain."""
    incomplete = {k: v for k, v in valid_schema().items() if k != "tier_vocabulary"}
    db_conn.execute(
        "INSERT INTO ontology_templates (name, version, schema, created_by) "
        "VALUES (%s, %s, %s, %s)",
        ("raw-broken-tpl", 1, json.dumps(incomplete), "bypass-admin"),
    )
    db_conn.commit()

    with pytest.raises(ValueError) as exc:
        workspaces.instantiate_domain(
            db_conn,
            key="dom-broken",
            name="Broken Domain",
            template_name="raw-broken-tpl",
            template_version=None,
            created_by="admin-1",
        )
    message = str(exc.value)
    assert "missing required key: tier_vocabulary" in message

    # 不产生域
    assert _count(db_conn, "domains", "WHERE key = %s", ("dom-broken",)) == 0
    assert _count(db_conn, "domains") == 0


def test_instantiation_is_data_operation_domain_visible_in_list(db_conn):
    """内核零改动 (data-operation evidence): instantiation works through the
    kernel store alone and the domain shows up in list_domains(). The
    no-kernel-file-changed half of the scenario is a CI-level gate."""
    make_domain(db_conn, "dom-vis")
    keys = [d["key"] for d in workspaces.list_domains(db_conn)]
    assert keys == ["dom-vis"]
    assert workspaces.list_domains(db_conn)[0]["template_name"] == "tpl-dom-vis"


# ------------------------------------------------------- membership audit


def test_role_change_is_append_only_with_audit_trail(db_conn):
    domain = make_domain(db_conn, "dom-mem")
    did = domain["id"]

    workspaces.add_member(
        db_conn, domain_id=did, user_id="u1", role="expert", added_by="admin-1"
    )
    changed = workspaces.change_member_role(
        db_conn, domain_id=did, user_id="u1", role="annotator", changed_by="lead-9"
    )
    assert changed["role"] == "annotator"
    assert changed["added_by"] == "lead-9"

    # one ACTIVE row only, showing the new role
    active = workspaces.list_members(db_conn, domain_id=did)
    assert len(active) == 1
    assert active[0]["user_id"] == "u1"
    assert active[0]["role"] == "annotator"
    assert active[0]["added_by"] == "lead-9"  # 新角色的操作者
    assert active[0]["removed_at"] is None

    # raw history for (domain, u1): TWO rows — the retired one keeps the old
    # role and its original added_by; only removed_at distinguishes them
    history = db_conn.execute(
        "SELECT id, role, added_by, removed_at FROM domain_members "
        "WHERE domain_id = %s AND user_id = %s ORDER BY id",
        (did, "u1"),
    ).fetchall()
    assert len(history) == 2

    old_row, new_row = history
    assert old_row["role"] == "expert"  # 变更前角色留痕
    assert old_row["added_by"] == "admin-1"  # original operator preserved
    assert old_row["removed_at"] is not None  # retired, not deleted
    assert new_row["role"] == "annotator"  # 变更后角色
    assert new_row["added_by"] == "lead-9"  # changed_by recorded on the new row
    assert new_row["removed_at"] is None

    # get_active_role follows the new role
    assert workspaces.get_active_role(db_conn, domain_id=did, user_id="u1") == "annotator"


def test_remove_member_retires_row_and_keeps_history(db_conn):
    domain = make_domain(db_conn, "dom-rm")
    did = domain["id"]
    workspaces.add_member(
        db_conn, domain_id=did, user_id="u2", role="lead", added_by="admin-1"
    )

    workspaces.remove_member(db_conn, domain_id=did, user_id="u2", removed_by="admin-1")

    # zero active rows, history rows remain
    assert workspaces.list_members(db_conn, domain_id=did) == []
    history = db_conn.execute(
        "SELECT role, added_by, removed_at FROM domain_members "
        "WHERE domain_id = %s AND user_id = %s",
        (did, "u2"),
    ).fetchall()
    assert len(history) == 1  # NOT deleted
    assert history[0]["role"] == "lead"
    assert history[0]["removed_at"] is not None

    assert workspaces.get_active_role(db_conn, domain_id=did, user_id="u2") is None

    # a re-added member is a fresh active row; history keeps growing
    workspaces.add_member(
        db_conn, domain_id=did, user_id="u2", role="annotator", added_by="admin-1"
    )
    assert workspaces.get_active_role(db_conn, domain_id=did, user_id="u2") == "annotator"
    total = _count(
        db_conn,
        "domain_members",
        "WHERE domain_id = %s AND user_id = %s",
        (did, "u2"),
    )
    assert total == 2


def test_add_member_rejects_unknown_role(db_conn):
    domain = make_domain(db_conn, "dom-role")
    with pytest.raises(ValueError, match="role must be one of"):
        workspaces.add_member(
            db_conn, domain_id=domain["id"], user_id="u3", role="owner", added_by="admin-1"
        )
    assert _count(db_conn, "domain_members") == 0


# ------------------------------------------------------- permission-aware list


def test_list_domains_filters_by_active_membership(db_conn):
    dom_a = make_domain(db_conn, "dom-a")
    dom_b = make_domain(db_conn, "dom-b")
    workspaces.add_member(
        db_conn, domain_id=dom_a["id"], user_id="alice", role="expert", added_by="admin-1"
    )

    # alice sees only her member domain
    seen = workspaces.list_domains(db_conn, user_id="alice")
    assert [d["key"] for d in seen] == ["dom-a"]

    # a non-member sees nothing — no B-domain data leaks
    assert workspaces.list_domains(db_conn, user_id="bob") == []

    # no user filter returns all domains
    assert [d["key"] for d in workspaces.list_domains(db_conn)] == ["dom-a", "dom-b"]

    # after removal alice's active membership is gone: filtered out again
    workspaces.remove_member(db_conn, domain_id=dom_a["id"], user_id="alice",
                             removed_by="admin-1")
    assert workspaces.list_domains(db_conn, user_id="alice") == []


# --------------------------------------------------------- invitations


def test_invitation_full_lifecycle_accept_then_invalid(db_conn):
    domain = make_domain(db_conn, "dom-inv")
    did = domain["id"]
    expires = datetime.now(timezone.utc) + timedelta(days=1)

    inv = workspaces.create_invitation(
        db_conn,
        domain_id=did,
        role="expert",
        invited_by="admin-1",
        expires_at=expires,
        token_hash="hash-token-1",
    )
    assert inv["token_hash"] == "hash-token-1"
    assert inv["domain_id"] == did
    assert inv["role"] == "expert"
    assert inv["accepted_at"] is None
    assert inv["accepted_by"] is None

    # only the digest is stored — retrievable by hash
    found = workspaces.get_invitation(db_conn, token_hash="hash-token-1")
    assert found["id"] == inv["id"]
    assert found["accepted_at"] is None

    accepted = workspaces.accept_invitation(
        db_conn, token_hash="hash-token-1", user_id="invitee-1"
    )
    assert accepted["accepted_at"] is not None
    assert accepted["accepted_by"] == "invitee-1"
    assert accepted["id"] == inv["id"]

    # membership created in the invited role
    assert workspaces.get_active_role(db_conn, domain_id=did, user_id="invitee-1") == "expert"
    members = workspaces.list_members(db_conn, domain_id=did)
    assert [(m["user_id"], m["role"]) for m in members] == [("invitee-1", "expert")]

    # second accept of the same hash — even by a different user — is refused
    with pytest.raises(InvitationError, match="already accepted"):
        workspaces.accept_invitation(
            db_conn, token_hash="hash-token-1", user_id="invitee-1"
        )
    with pytest.raises(InvitationError, match="already accepted"):
        workspaces.accept_invitation(
            db_conn, token_hash="hash-token-1", user_id="invitee-2"
        )
    # and no membership appeared for the second user
    assert workspaces.get_active_role(db_conn, domain_id=did, user_id="invitee-2") is None

    # invitation row is consumed exactly once: accepted_at/accepted_by unchanged
    final = workspaces.get_invitation(db_conn, token_hash="hash-token-1")
    assert final["accepted_by"] == "invitee-1"

    # unknown hash
    with pytest.raises(InvitationError, match="unknown"):
        workspaces.accept_invitation(
            db_conn, token_hash="hash-never-issued", user_id="invitee-3"
        )


def test_expired_invitation_rejected_and_no_membership_created(db_conn):
    domain = make_domain(db_conn, "dom-exp")
    did = domain["id"]
    past = datetime.now(timezone.utc) - timedelta(hours=1)

    workspaces.create_invitation(
        db_conn,
        domain_id=did,
        role="lead",
        invited_by="admin-1",
        expires_at=past,
        token_hash="hash-expired",
    )

    with pytest.raises(InvitationError, match="expired"):
        workspaces.accept_invitation(
            db_conn, token_hash="hash-expired", user_id="late-user"
        )

    # 不产生成员记录: no membership row at all, invitation still unconsumed
    assert _count(
        db_conn,
        "domain_members",
        "WHERE domain_id = %s AND user_id = %s",
        (did, "late-user"),
    ) == 0
    assert workspaces.get_active_role(db_conn, domain_id=did, user_id="late-user") is None
    assert workspaces.get_invitation(db_conn, token_hash="hash-expired")["accepted_at"] is None
