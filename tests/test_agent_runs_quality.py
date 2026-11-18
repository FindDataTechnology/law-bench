"""运行台账与质量比：四态结局、进度不变量、六项可复算比率。

这组测试钉的都是"数字会不会骗人"的那一面：

- `thin` 与 `failed` 必须分得开（前者升级给人，后者不许用重试掩盖）；
- 只有读类失败允许重试（写了一半再重跑的账最难解释）；
- 剩余量不下降即停（分批不收敛实测过两次）；
- 六项比率分母为 0 时报 `None` 而不是 0；
- 判官健康没有实探就报"未探"，不得报通过。
"""

from __future__ import annotations

import pytest

import packs.legal  # noqa: F401 — registers fold rules
from src.bench import agent_runs, authoring, proposals, quality, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema

SCHEMA = {
    "entity_types": ["clause", "law", "concept"],
    "concept_structures": {"clause": ["id"]},
    "relationship_kinds": ["defines"],
    "tier_vocabulary": list(TIERS),
    "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
    "corpus_declaration": {"source_types": []},
}

AGENT = "agent:concept@legal"


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    templates.create_template(conn=empty_db, name="tpl", schema=dict(SCHEMA), created_by="t")
    workspaces.instantiate_domain(
        conn=empty_db, key="legal", name="法律域", template_name="tpl",
        template_version=None, created_by="t",
    )
    # add-fleet-execution-loop: fleet: sources now need a live registration.
    from _fleet_fixtures import provision_default_fleet_world
    provision_default_fleet_world(empty_db)
    yield empty_db
    from src.eval.db import close_shared_conn
    close_shared_conn()


# ── 台账 ────────────────────────────────────────────────────────────────────


def test_only_agents_get_a_ledger_row(conn):
    with pytest.raises(ValueError, match="只记智能体的轮次"):
        agent_runs.start(conn, role="aloadtree@gmail.com", domain_key="legal")


def test_unknown_domain_is_refused(conn):
    with pytest.raises(ValueError, match="not found"):
        agent_runs.start(conn, role=AGENT, domain_key="no-such-domain")


def test_a_run_records_counts_and_outcome(conn):
    run = agent_runs.start(conn, role=AGENT, domain_key="legal",
                           input_digest="sha256:abc", run_key="batch-1")
    assert run["outcome"] == "running"
    done = agent_runs.finish(conn, run_id=run["id"], outcome="ok",
                             counts={"produced": 12, "submitted": 8},
                             remaining=0, artifact_refs=[{"batch": "batch-1"}])
    assert done["outcome"] == "ok"
    assert done["counts"] == {"produced": 12, "submitted": 8}
    assert done["ended_at"] is not None


def test_finishing_twice_does_not_rewrite_the_outcome(conn):
    run = agent_runs.start(conn, role=AGENT, domain_key="legal")
    agent_runs.finish(conn, run_id=run["id"], outcome="thin")
    again = agent_runs.finish(conn, run_id=run["id"], outcome="ok")
    assert again["outcome"] == "thin"


def test_running_is_not_a_conclusion(conn):
    run = agent_runs.start(conn, role=AGENT, domain_key="legal")
    with pytest.raises(ValueError, match="running"):
        agent_runs.finish(conn, run_id=run["id"], outcome="running")


def test_only_read_only_failures_may_retry():
    assert agent_runs.may_retry("failed", read_only=True)
    assert not agent_runs.may_retry("failed", read_only=False)
    assert not agent_runs.may_retry("thin", read_only=True)
    assert not agent_runs.may_retry("ok", read_only=True)


def test_progress_invariant():
    assert agent_runs.should_stop(200, 200) is True     # 不下降 = 停
    assert agent_runs.should_stop(200, 210) is True
    assert agent_runs.should_stop(200, 199) is False
    assert agent_runs.should_stop(None, 10) is False    # 首轮没有前值


def test_summary_groups_by_outcome(conn):
    for outcome in ("ok", "ok", "thin"):
        run = agent_runs.start(conn, role=AGENT, domain_key="legal")
        agent_runs.finish(conn, run_id=run["id"], outcome=outcome)
    s = agent_runs.summary(conn, domain_key="legal")
    assert s["by_outcome"]["ok"] == 2
    assert s["by_outcome"]["thin"] == 1
    assert s["last"]["outcome"] in ("ok", "thin")


# ── 质量比 ──────────────────────────────────────────────────────────────────


def test_empty_domain_reports_none_not_zero(conn):
    m = quality.all_metrics(conn, domain_key="legal")
    assert m["grounding"]["value"] is None
    assert m["evidence"]["value"] is None
    assert m["referential"]["value"] is None
    assert m["review_lag"]["value"] is None
    assert m["judge"]["value"] is None and m["judge"]["probed"] is False


def test_grounding_counts_only_grounded_concepts(conn):
    authoring.authoring_create_unit(conn, domain_key="legal", kind="concept",
                                    external_key="违约金调整", body="b", operator="t")
    authoring.authoring_create_unit(conn, domain_key="legal", kind="concept",
                                    external_key="举证责任", body="b", operator="t")
    authoring.authoring_create_unit(conn, domain_key="legal", kind="clause",
                                    external_key="合同法#第585条", body="b", operator="t")
    authoring.authoring_create_relationship(
        conn, domain_key="legal", kind="defines",
        from_key="违约金调整", to_key="合同法#第585条",
        body="违约金调整 defines 合同法#第585条", operator="t")
    m = quality.grounding(conn, namespace="legal")
    assert (m["numerator"], m["denominator"]) == (1, 2)
    assert m["value"] == 0.5
    assert m["gaps"] == ["举证责任"]


def test_evidence_rate_lists_the_kinds_that_lack_it(conn):
    authoring.authoring_create_unit(
        conn, domain_key="legal", kind="clause", external_key="合同法#第1条",
        body="b", operator="t", attrs={"chunk_id": "c1"})
    authoring.authoring_create_unit(
        conn, domain_key="legal", kind="law", external_key="合同法", body="b",
        operator="t", attrs={"corpus": {"library": "law-library"}})
    m = quality.evidence(conn, namespace="legal")
    assert (m["numerator"], m["denominator"]) == (1, 2)
    assert m["gaps"] == [{"kind": "law", "missing": 1}]


def test_dangling_relation_is_visible(conn):
    authoring.authoring_create_unit(conn, domain_key="legal", kind="concept",
                                    external_key="违约金调整", body="b", operator="t")
    # 直接造一条端点不存在的活关系（模拟退文档不退关系的现场）
    conn.execute(
        "INSERT INTO knowledge_units (kind, namespace, external_key, body, created_at, updated_at) "
        "VALUES ('defines','legal','违约金调整->defines:合同法#第585条','x','now','now')"
    )
    conn.commit()
    m = quality.referential_integrity(conn, namespace="legal")
    assert (m["numerator"], m["denominator"]) == (0, 1)
    assert m["gaps"] == ["违约金调整->defines:合同法#第585条"]


def test_review_lag_reports_pending_and_threshold(conn):
    proposals.submit(conn, domain_key="legal", source="fleet:a/1", kind="concept",
                     external_key="违约金调整", body="b",
                     evidence={"quote": "q"}, submitted_by="fleet:a/1")
    m = quality.review_lag(conn, domain_key="legal", threshold_hours=24)
    assert m["pending"] == 1
    assert m["value"] is not None and m["value"] >= 0
    assert m["over_threshold"] is False


def test_key_hygiene_counts_keys_that_would_still_fold(conn):
    conn.execute(
        "INSERT INTO knowledge_units (kind, namespace, external_key, body, created_at, updated_at) "
        "VALUES ('law','legal','中华人民共和国合同法','x','now','now')"
    )
    conn.execute(
        "INSERT INTO knowledge_units (kind, namespace, external_key, body, created_at, updated_at) "
        "VALUES ('law','legal','公司法','x','now','now')"
    )
    conn.commit()
    m = quality.key_hygiene(conn, domain_key="legal", namespace="legal")
    assert (m["numerator"], m["denominator"]) == (1, 2)
    assert m["gaps"][0]["folds_to"] == "合同法"


def test_key_hygiene_is_none_without_rules(conn):
    m = quality.key_hygiene(conn, domain_key="no-pack-line", namespace="legal")
    assert m["value"] is None
    assert "未注册归名规则" in m["how"]


def test_judge_health_needs_a_real_probe():
    assert quality.judge_health()["value"] is None
    assert quality.judge_health(probed={"ok": False, "status": 400,
                                        "detail": "InvalidSubscription"})["value"] == 0.0
    assert quality.judge_health(probed={"ok": True, "status": 200})["value"] == 1.0
