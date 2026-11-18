"""岗位注册表：参数属于线，机制属于内核。

三件事：

- pack 里的 `roles` 段是唯一参数来源，内核不认识任何行业；
- 未知岗位名 / 未知参数 / 类型不对一律报错，不静默忽略（拼写错误是最难查的配置事故）；
- 未声明的线不启动，并说清"未声明"，不套用别的线的默认值。
"""

from __future__ import annotations

import pytest

import packs.legal  # noqa: F401 — 注册归名规则（与 web 边缘一致）
from src.bench import agent_team, packs

BASE = {
    "name": "demo",
    "version": "0.1.0",
    "description": "d",
    "kinds": ["clause"],
    "components": [],
    "eval_suites": [],
}


def _manifest(**roles):
    return {**BASE, "roles": roles}


# ── 词表与参数校验 ──────────────────────────────────────────────────────────


def test_role_vocabulary_is_closed():
    assert set(agent_team.ROLES) == {
        "scout", "builder", "concept", "verifier", "eval", "release", "warden"
    }


def test_unknown_role_is_refused():
    with pytest.raises(agent_team.RoleDeclarationError, match="未知岗位"):
        agent_team.declared_roles(_manifest(consept={"enabled": True}), pack_name="demo")


def test_unknown_param_is_refused():
    """拼错的参数名必须报错，否则它会被静默忽略、跑成默认行为。"""
    with pytest.raises(agent_team.RoleDeclarationError, match="未知参数"):
        agent_team.declared_roles(
            _manifest(concept={"enabled": True, "batch_chunk": 10}), pack_name="demo")


def test_types_are_checked():
    with pytest.raises(agent_team.RoleDeclarationError, match="enabled"):
        agent_team.declared_roles(_manifest(warden={"enabled": "yes"}), pack_name="demo")
    with pytest.raises(agent_team.RoleDeclarationError, match="cadence_minutes"):
        agent_team.declared_roles(_manifest(warden={"cadence_minutes": 0}), pack_name="demo")


def test_roles_must_be_a_mapping():
    with pytest.raises(agent_team.RoleDeclarationError, match="必须是映射"):
        agent_team.declared_roles({**BASE, "roles": ["warden"]}, pack_name="demo")


def test_absent_roles_section_is_empty_not_an_error():
    assert agent_team.declared_roles(BASE) == {}


# ── 两条真实线 ──────────────────────────────────────────────────────────────


def test_legal_declares_readonly_and_write_roles():
    plan = agent_team.plan("legal")
    roles = {r["role"]: r for r in plan["runnable"]}
    assert plan["declared"] is True
    assert roles["warden"]["cadence_minutes"] == 15
    assert roles["concept"]["params"]["batch_chunks"] == 10
    # 未声明的岗位不起——eval / release 在 legal 里没有声明
    assert "eval" in plan["skipped"] and "release" in plan["skipped"]


def test_gov_declares_its_own_parameters():
    plan = agent_team.plan("gov")
    roles = {r["role"]: r for r in plan["runnable"]}
    assert plan["declared"] is True
    # 政务线的文种与法律线不同，参数各自声明，互不影响
    assert "办法" in roles["scout"]["params"]["doc_types"]
    # 概念岗为此线新开（add-gov-concept-layer）：语料面就是本域唯一订阅的政务全文。
    # 此前这里断言 "concept" in plan["skipped"]——那时政务线不产概念，于是
    # grounding 的分母恒为 0、永远读 None。
    assert roles["concept"]["params"]["sources"] == ["gov"]
    assert "eval" in plan["skipped"] and "release" in plan["skipped"]


def test_write_roles_have_no_default_cadence():
    """写类的节奏是业务决定；没声明就是 None，不替它猜一个数字。"""
    assert agent_team.cadence_minutes("concept", {}) is None
    assert agent_team.cadence_minutes("warden", {}) == 15


# ── 未声明的线 ──────────────────────────────────────────────────────────────


def test_an_undeclared_line_does_not_start(monkeypatch):
    plan = agent_team.plan("no-such-line")
    assert plan["declared"] is False
    assert plan["runnable"] == []
    assert "未声明" in plan["reason"]


def test_a_pack_without_roles_does_not_start(monkeypatch):
    monkeypatch.setattr(packs, "load_pack", lambda name: dict(BASE))
    plan = agent_team.plan("demo")
    assert plan["declared"] is False
    assert "没有 roles 段" in plan["reason"]


def test_plan_never_writes(monkeypatch):
    """计划是纯读：编排层刷新一次不该变成一次配置变更。"""
    calls = []
    monkeypatch.setattr(packs, "load_pack",
                        lambda name: calls.append(name) or dict(_manifest(warden={})))
    agent_team.plan("demo")
    assert calls == ["demo"]


def test_validate_pack_catches_a_bad_roles_section():
    problems = packs.validate_pack(_manifest(warden={"enabled": "yes"}))
    assert any("enabled" in p for p in problems)


def test_validate_pack_accepts_the_real_packs():
    for name in ("legal", "gov"):
        manifest = packs.load_pack(name)
        assert packs.validate_pack(manifest, directory=name) == []


def test_a_concept_role_may_declare_its_corpus_face():
    """概念只从某类语料里来，所以 `sources` 必须是它可声明的参数。

    实测：抽 statutes 得 0 条候选——概念长在裁判说理里。而白名单最初没放行
    `sources`，pack 里写了会被判"未知参数"→整条线 declared=False（守卫本身是对的，
    缺的是这个词表项）。
    """
    roles = agent_team.roles_for_domain("legal")
    assert roles["declared"] is True
    assert roles["roles"]["concept"]["sources"] == ["judicial", "guide_cases"]


def test_the_concept_run_passes_the_declared_sources_to_extraction(monkeypatch):
    """run_concept 必须把声明过的语料面传下去，不能抽全范围。

    用 stub 把 extraction.run 换掉，只验一件事：sources 有没有被传下去。
    """
    import src.bench.extraction as extraction_mod
    from src.bench import agent_runs, team_roles

    seen: dict = {}

    def fake_run(conn, **kw):
        seen.update(kw)
        return {"sampled": 0, "produced": 0, "submitted": 0, "duplicate": 0,
                "usable_rate": 0.0, "by_kind": {}, "skipped": {}, "stopped": None}

    monkeypatch.setattr(extraction_mod, "run", fake_run)
    monkeypatch.setattr(team_roles, "_role_params",
                        lambda d, r: {"batch_chunks": 3, "min_usable_rate": 0.5,
                                      "max_total": 9, "sources": ["guide_cases"]})
    monkeypatch.setattr(agent_runs, "start", lambda *a, **k: {"id": 1})
    monkeypatch.setattr(agent_runs, "finish", lambda *a, **k: {"id": 1, "outcome": "thin"})

    team_roles.run_concept(object(), domain_key="legal", batch="b-x")
    assert seen["sources"] == ["guide_cases"]
    assert seen["max_chunks"] == 3 and seen["max_total"] == 9
