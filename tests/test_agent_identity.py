"""智能体身份：两道闸，以及"谁算智能体"只有一个口径。

两条不变量，都是"漏了就静默放行"的那种：

- **铸凭据时**：`agent:` 身份拿不到 `admin`/`*`。拿到的话，confirm 的 admin 豁免
  就能替它自己的提案背书。
- **确认时**：agent 不能当签字人（任何提案），且 admin 豁免对 agent 提交的提案
  无效。人工 lead 正常确认 agent 的提案仍然可以——那正是这套设计的正常路径。
"""

from __future__ import annotations

import pytest

import packs.legal  # noqa: F401 — registers the fold rules
from src.bench import agent_ids, proposals, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema
from src.web.auth import apikey

SCHEMA = {
    "entity_types": ["clause", "law", "concept"],
    "concept_structures": {"clause": ["id"]},
    "relationship_kinds": ["defines"],
    "tier_vocabulary": list(TIERS),
    "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
    "corpus_declaration": {"source_types": []},
}


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    templates.create_template(conn=empty_db, name="tpl", schema=dict(SCHEMA), created_by="t")
    workspaces.instantiate_domain(
        conn=empty_db, key="legal", name="法律域", template_name="tpl",
        template_version=None, created_by="t",
    )
    # The minted identity these tests submit as must be a live member of the
    # domain (add-fleet-execution-loop tightened ``agent:`` source validation).
    from _fleet_fixtures import add_agent_member, register_fleet

    add_agent_member(empty_db, "agent:concept@legal", domain_key="legal")
    register_fleet(empty_db, "a", ["legal"])
    yield empty_db
    from src.eval.db import close_shared_conn
    close_shared_conn()


def _submit(conn, *, source="agent:concept@legal", key="违约金调整", submitted_by=None,
            authenticated_as=None):
    return proposals.submit(
        conn, domain_key="legal", source=source, kind="concept", external_key=key,
        body="违约金的调整规则", evidence={"quote": "违约金过高可以请求减少"},
        submitted_by=submitted_by or source,
        # The caller is the identity being claimed: an agent submits as itself.
        authenticated_as=authenticated_as if authenticated_as is not None else source,
    )


# ── 身份口径 ────────────────────────────────────────────────────────────────


def test_only_the_agent_prefix_marks_an_agent():
    assert agent_ids.is_agent("agent:concept@legal")
    assert not agent_ids.is_agent("aloadtree@gmail.com")
    assert not agent_ids.is_agent("fleet:abc/post-7")
    assert not agent_ids.is_agent("")
    assert not agent_ids.is_agent(None)


def test_identity_is_built_from_role_and_domain():
    assert agent_ids.agent_identity("concept", "legal") == "agent:concept@legal"
    with pytest.raises(ValueError):
        agent_ids.agent_identity("", "legal")
    with pytest.raises(ValueError):
        agent_ids.agent_identity("concept", "legal@x")


# ── 第一道闸：铸凭据 ────────────────────────────────────────────────────────


def test_an_agent_key_cannot_carry_admin(conn):
    with pytest.raises(ValueError, match="不得持有平台级权限"):
        apikey.create_key("agent:concept@legal", "concept", ["content:read", "admin"],
                          db_path=conn)
    with pytest.raises(ValueError, match="不得持有平台级权限"):
        apikey.create_key("agent:concept@legal", "concept", ["*"], db_path=conn)


def test_an_agent_key_with_normal_scopes_is_fine(conn):
    key = apikey.create_key("agent:concept@legal", "concept",
                            ["content:read", "content:write"], db_path=conn)
    resolved = apikey.verify_key(key, db_path=conn)
    assert resolved["sub"] == "agent:concept@legal"
    assert resolved["scopes"] == ["content:read", "content:write"]


def test_a_human_key_may_still_be_admin(conn):
    apikey.create_key("ops@example.com", "ops", ["admin"], db_path=conn)


# ── 第二道闸：确认 ──────────────────────────────────────────────────────────


def test_an_agent_can_never_confirm(conn):
    proposal = _submit(conn)
    with pytest.raises(PermissionError, match="机器身份不得确认提案"):
        proposals.confirm(conn, domain_key="legal", proposal_id=proposal["id"],
                          actor="agent:verifier@legal", admin_override=False)


def test_admin_override_does_not_sign_for_an_agent(conn):
    """The exemption is for humans putting out fires, not for machines signing."""
    proposal = _submit(conn)
    with pytest.raises(PermissionError, match="管理员豁免不适用于机器身份提交的提案"):
        proposals.confirm(conn, domain_key="legal", proposal_id=proposal["id"],
                          actor="ops@example.com", admin_override=True)


def test_a_human_lead_confirms_an_agent_proposal_normally(conn):
    proposal = _submit(conn)
    confirmed = proposals.confirm(
        conn, domain_key="legal", proposal_id=proposal["id"],
        actor="lead@example.com", admin_override=False,
    )
    assert confirmed["state"] == "confirmed"
    row = conn.execute(
        "SELECT external_key FROM knowledge_units WHERE namespace='legal' AND kind='concept'"
    ).fetchone()
    assert row["external_key"] == "违约金调整"


def test_a_human_may_still_confirm_their_own_with_override(conn):
    """The human escape hatch is unchanged — only agents lost it."""
    proposal = _submit(conn, source="user:expert@example.com", key="举证责任",
                       submitted_by="expert@example.com",
                       authenticated_as="expert@example.com")
    confirmed = proposals.confirm(
        conn, domain_key="legal", proposal_id=proposal["id"],
        actor="expert@example.com", admin_override=True,
    )
    assert confirmed["state"] == "confirmed"


# ── 登记脚本的两条前置拒绝（不触库） ────────────────────────────────────────


def test_register_script_refuses_admin_scope_before_touching_the_db(capsys):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import register_agent

    rc = register_agent.main(["--role", "concept", "--domain", "legal",
                              "--scopes", "content:read,admin", "--dry-run"])
    assert rc == 2
    assert "不得持有平台级权限" in capsys.readouterr().err


def test_register_script_refuses_lead_membership(capsys):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import register_agent

    rc = register_agent.main(["--role", "concept", "--domain", "legal",
                              "--member-role", "lead", "--dry-run"])
    assert rc == 2
    assert "lead" in capsys.readouterr().err
