"""只读岗位：巡检派单、质检标注。两个都不能写本体。

要钉住的是"只读"这件事本身：

- 巡检员只创建任务（幂等）与台账行，不动 `knowledge_units`；
- 质检员只出 findings，不改提案状态、不写单位；
- 拿不到语料原文时，引文核对报 `quote_unverifiable` 而不是通过——
  把"没法验"记成"验过了"，是替人签字；
- 失败也留台账（`failed` + 错误原话），不是静默什么都不发生。
"""

from __future__ import annotations

import pytest

import packs.legal  # noqa: F401 — 归名规则与 web 边缘一致
from src.bench import (agent_runs, authoring, proposals, team_roles, templates,
                       workspaces)
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


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    # rubrics/criteria 来自遗留 seed（src/eval/harbor_seed.py），不在 ensure_schema
    # 里；评测柱会读它们，所以按已部署形状补建——与 tests/test_estate_matrix.py
    # 同一做法，避免两处对"表该长什么样"各写一套。
    empty_db.execute(
        """
        CREATE TABLE IF NOT EXISTS rubrics (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name TEXT NOT NULL,
            context TEXT,
            source TEXT,
            source_path TEXT,
            description TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    empty_db.execute(
        """
        CREATE TABLE IF NOT EXISTS criteria (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            rubric_id BIGINT NOT NULL REFERENCES rubrics(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT,
            guidance TEXT,
            ordinal INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    empty_db.commit()
    from src.eval import store as eval_store
    eval_store._ensured_dbs.clear()
    ensure_schema(db_path=empty_db)
    templates.create_template(conn=empty_db, name="tpl", schema=dict(SCHEMA), created_by="t")
    workspaces.instantiate_domain(
        conn=empty_db, key="legal", name="法律域", template_name="tpl",
        template_version=None, created_by="t",
    )
    # add-fleet-execution-loop: the proposal tests here submit with fleet:a/1 and
    # agent:concept@legal, which now need a live registration / membership.
    from _fleet_fixtures import provision_default_fleet_world

    provision_default_fleet_world(empty_db, domains=["legal"])
    yield empty_db
    from src.eval.db import close_shared_conn
    close_shared_conn()


def _unit(conn, kind="clause", key="合同法#第1条", attrs=None):
    authoring.authoring_create_unit(
        conn, domain_key="legal", kind=kind, external_key=key, body="b",
        operator="t", attrs=attrs,
    )


def _submit(conn, *, kind="concept", key="违约金调整", evidence=None, source="fleet:a/1"):
    return proposals.submit(
        conn, domain_key="legal", source=source, kind=kind, external_key=key,
        body="b", evidence=evidence if evidence is not None else {"quote": "q"},
        submitted_by=source,
    )


# ── 巡检员 ──────────────────────────────────────────────────────────────────


def test_warden_dispatches_a_quality_gap_to_the_owning_role(conn):
    _unit(conn)  # 有单位但没有依据 → quality:evidence
    out = team_roles.run_warden(conn, domain_key="legal")
    assert "quality:evidence" in out["gaps"]
    tasks = conn.execute(
        "SELECT assignee, target_key, status FROM authoring_tasks "
        "WHERE target_key = 'quality:evidence'").fetchall()
    assert len(tasks) == 1
    assert tasks[0]["assignee"] == "agent:builder@legal"


def test_warden_is_idempotent_across_runs(conn):
    _unit(conn)
    first = team_roles.run_warden(conn, domain_key="legal")
    second = team_roles.run_warden(conn, domain_key="legal")
    assert first["tasks_created"] >= 1
    assert second["tasks_created"] == 0
    assert second["already_open"] >= 1
    # 每个可派缺口恰好一条任务：重复巡检不堆叠
    total = conn.execute("SELECT COUNT(*) AS n FROM authoring_tasks").fetchone()["n"]
    per_gap = conn.execute(
        "SELECT target_key, COUNT(*) AS n FROM authoring_tasks GROUP BY target_key").fetchall()
    assert total == len(per_gap)
    assert all(r["n"] == 1 for r in per_gap)


def test_warden_leaves_the_ontology_untouched(conn):
    _unit(conn)
    before = conn.execute("SELECT COUNT(*) AS n FROM knowledge_units").fetchone()["n"]
    team_roles.run_warden(conn, domain_key="legal")
    after = conn.execute("SELECT COUNT(*) AS n FROM knowledge_units").fetchone()["n"]
    assert before == after


def test_warden_sends_review_backlog_to_a_human(conn):
    """复核积压不派给智能体：确认权不在它们手上，派了也做不了。"""
    p = _submit(conn)
    # 只有"最老一条超过阈值"才算积压，所以把它拨回 48 小时前
    conn.execute(
        "UPDATE domain_proposals SET submitted_at = now() - interval '48 hours' WHERE id = %s",
        (p["id"],))
    conn.commit()
    out = team_roles.run_warden(conn, domain_key="legal")
    assert "quality:review_lag" in out["skipped"]
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM authoring_tasks WHERE target_key = 'quality:review_lag'"
    ).fetchone()["n"] == 0


def test_warden_writes_a_ledger_row(conn):
    _unit(conn)
    out = team_roles.run_warden(conn, domain_key="legal")
    run = out["run"]
    assert run["role"] == "agent:warden@legal"
    assert run["outcome"] == "ok"
    assert run["counts"]["gap_count"] == len(out["gaps"])
    assert run["ended_at"] is not None


def test_warden_records_a_failure_instead_of_vanishing(conn, monkeypatch):
    """失败也要留痕——包括"进程里已经炸了、事务已中止"的那种。

    这里让 estestate.matrix 抛错来制造真实的失败路径：如果实现里没有先回滚，
    写台账那一步会再失败，台账就空了（这正是修之前的样子）。
    """
    _unit(conn)

    def boom(*a, **kw):
        raise RuntimeError("矩阵算不出来")

    monkeypatch.setattr(team_roles.estate, "matrix", boom)
    with pytest.raises(RuntimeError):
        team_roles.run_warden(conn, domain_key="legal")
    rows = agent_runs.list_runs(conn, domain_key="legal", role="agent:warden@legal")
    assert rows and rows[0]["outcome"] == "failed"
    assert "矩阵算不出来" in (rows[0]["detail"] or "")


# ── 质检员 ──────────────────────────────────────────────────────────────────


def test_verifier_flags_a_key_that_already_exists(conn):
    # 真实成因：提案先进箱，之后同一个键被别人确认为活单位 ⇒ 这条待确认提案
    # 已经重复。提交口预检（refuse-unlandable-proposals）挡的是「先有单位再提」，
    # 挡不住、也不该挡这个竞态——质检员要看的正是它。
    _submit(conn, key="违约金调整")
    _unit(conn, kind="concept", key="违约金调整")
    out = team_roles.run_verifier(conn, domain_key="legal")
    assert out["by_check"]["key_already_live"] == 1
    assert out["clean"] == 0


def test_verifier_flags_an_open_relationship_endpoint(conn):
    # 「端点开着的待确认提案」只能由**事后**变化产生：提交口预检
    # （refuse-unlandable-proposals）已经不允许带着未闭合端点提交。真实成因是
    # 端点先存在、关系进箱、之后端点被软删——这条用例就按这个顺序构造。
    _unit(conn, kind="concept", key="违约金调整")
    _unit(conn, kind="concept", key="合同法#第585条")
    _submit(conn, kind="defines", key="违约金调整->defines:合同法#第585条",
            evidence={"from_key": "违约金调整", "to_key": "合同法#第585条", "quote": "q"})
    authoring.authoring_delete_unit(
        conn, domain_key="legal", kind="concept", external_key="合同法#第585条",
        operator="t",
    )
    out = team_roles.run_verifier(conn, domain_key="legal")
    assert out["by_check"]["endpoint_open"] == 1


def test_verifier_says_it_could_not_verify_a_quote(conn):
    """拿不到语料原文时报"没法验"，不报通过。"""
    _submit(conn, key="举证责任", evidence={"quote": "某段原文", "chunk_id": "c1"})
    out = team_roles.run_verifier(conn, domain_key="legal")
    assert out["by_check"]["quote_unverifiable"] == 1


def test_verifier_flags_one_claim_with_two_different_evidences(conn):
    """同一主张、**不同依据**会合法地并存两行，这才是该标 near_duplicate 的情形。

    同键同依据不再产生两行（提案层按主张去重并合并 sources），所以旧的
    "两个生产者同键 = 两行"前提已经不成立——那条性质由
    tests/test_domain_proposals.py 断言。
    """
    _submit(conn, key="举证责任", source="fleet:a/1",
            evidence={"quote": "第一种说法"})
    _submit(conn, key="举证责任", source="agent:concept@legal",
            evidence={"quote": "第二种说法"})
    out = team_roles.run_verifier(conn, domain_key="legal")
    assert out["by_check"]["near_duplicate"] == 1


def test_the_same_claim_with_the_same_evidence_is_one_row_not_a_duplicate(conn):
    """同键同依据只留一行，质检不该把它报成重复。"""
    _submit(conn, key="举证责任", source="fleet:a/1", evidence={"quote": "同一说法"})
    _submit(conn, key="举证责任", source="agent:concept@legal", evidence={"quote": "同一说法"})
    out = team_roles.run_verifier(conn, domain_key="legal")
    assert out["pending"] == 1
    assert out["by_check"].get("near_duplicate", 0) == 0


def test_verifier_never_changes_a_proposal_or_the_ontology(conn):
    p = _submit(conn, key="违约金调整")
    _unit(conn, kind="concept", key="违约金调整")
    before_units = conn.execute("SELECT COUNT(*) AS n FROM knowledge_units").fetchone()["n"]
    team_roles.run_verifier(conn, domain_key="legal")
    state = conn.execute("SELECT state FROM domain_proposals WHERE id = %s",
                         (p["id"],)).fetchone()["state"]
    after_units = conn.execute("SELECT COUNT(*) AS n FROM knowledge_units").fetchone()["n"]
    assert state == "pending"
    assert before_units == after_units


def test_verifier_with_an_empty_inbox_reports_thin(conn):
    out = team_roles.run_verifier(conn, domain_key="legal")
    assert out["run"]["outcome"] == "thin"
    assert out["pending"] == 0 and out["findings"] == []


# ── 逐字核验（新增能力：把"没法验"升级成真判定） ──────────────────────────


def test_a_quote_that_is_in_the_source_passes(conn, monkeypatch):
    """引文逐字命中 → 不产生 finding（干净的就是干净的）。"""
    _submit(conn, key="举证责任",
            evidence={"quote": "合同应当采用书面形式", "library": "law-library",
                      "source_key": "statutes", "chunk_id": "c1"})
    monkeypatch.setattr(team_roles, "fetch_chunk_text",
                        lambda *a, **kw: "第一条 为了规范。第二条 合同应当采用书面形式。")
    out = team_roles.run_verifier(conn, domain_key="legal")
    assert out["by_check"].get("quote_mismatch", 0) == 0
    assert out["by_check"].get("quote_unverifiable", 0) == 0


def test_a_fabricated_quote_is_flagged(conn, monkeypatch):
    _submit(conn, key="举证责任",
            evidence={"quote": "这句话原文里没有", "library": "law-library",
                      "source_key": "statutes", "chunk_id": "c1"})
    monkeypatch.setattr(team_roles, "fetch_chunk_text",
                        lambda *a, **kw: "第一条 为了规范合同的订立。")
    out = team_roles.run_verifier(conn, domain_key="legal")
    assert out["by_check"]["quote_mismatch"] == 1


def test_when_the_chunk_cannot_be_fetched_it_still_says_unverifiable(conn, monkeypatch):
    """取不到原文绝不等于核验通过。"""
    _submit(conn, key="举证责任",
            evidence={"quote": "某句", "library": "law-library",
                      "source_key": "statutes", "chunk_id": "gone"})
    monkeypatch.setattr(team_roles, "fetch_chunk_text", lambda *a, **kw: None)
    out = team_roles.run_verifier(conn, domain_key="legal")
    assert out["by_check"]["quote_unverifiable"] == 1
