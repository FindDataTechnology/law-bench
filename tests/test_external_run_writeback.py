"""External run write-back (add-fleet-execution-loop §3).

三条规则在这里被钉住：

- **幂等靠存在性检查，不靠唯一索引**：``runner_ref`` 为空是合法情形（内核岗位有
  不传 ``run_key`` 的用例），而空值不参与唯一性——加唯一索引会得到「看起来防住了、
  实际没防」的假安全感。
- **来源分列**：内核岗位 ``origin='kernel'`` 且 ``runner_ref`` 为空；舰队回写
  ``origin='fleet'`` 且 ``runner_ref`` 必填。这条是「值班长能一眼看出谁在跑」的
  全部实现。
- **回写不污染质量比**：``counts`` 只进台账展示，比率仍由库内真实内容重算。
"""

from __future__ import annotations

import pytest

from src.bench import agent_runs, submitters, templates, workspaces


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    from src.bench.promotion import SENSITIVITY_LEVELS
    from src.bench.tiers import TIERS
    from src.eval.store import ensure_schema

    ensure_schema(db_path=empty_db)
    schema = {
        "entity_types": ["company"],
        "concept_structures": {},
        "relationship_kinds": ["belongs_to"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {},
    }
    templates.create_template(conn=empty_db, name="tpl", schema=schema, created_by="t")
    workspaces.instantiate_domain(
        conn=empty_db, key="legal", name="法律域", template_name="tpl",
        template_version=None, created_by="t",
    )
    yield empty_db


def _fleet_run(conn, ref="fleet:test-fleet/post-1#2026-11-13", **kw):
    params = dict(
        runner_ref=ref, role="concept", domain_key="legal", outcome="ok",
        counts={"drafts": 3}, artifact_refs=[{"proposal_id": 1}], detail="跑完",
    )
    params.update(kw)
    return agent_runs.record_external_run(conn, **params)


def test_kernel_runs_are_marked_kernel(conn):
    run = agent_runs.start(conn, role="agent:warden@legal", domain_key="legal")
    assert run["origin"] == "kernel"
    assert run["runner_ref"] is None


def test_external_run_is_marked_fleet(conn):
    run, created = _fleet_run(conn)
    assert created is True
    assert run["origin"] == "fleet"
    assert run["runner_ref"] == "fleet:test-fleet/post-1#2026-11-13"
    assert run["outcome"] == "ok"


def test_replay_is_idempotent_and_changes_nothing(conn):
    first, created = _fleet_run(conn)
    assert created is True
    again, created_again = _fleet_run(conn, outcome="failed", counts={"drafts": 99})
    assert created_again is False
    assert again["id"] == first["id"]
    # A replay must not rewrite the recorded outcome or counts.
    assert again["outcome"] == "ok"
    assert again["counts"]["drafts"] == 3

    n = conn.execute(
        "SELECT count(*) AS n FROM domain_agent_runs WHERE origin = 'fleet'"
    ).fetchone()["n"]
    assert n == 1


def test_outcome_outside_the_vocabulary_is_refused(conn):
    for bad in ("running", "done", ""):
        with pytest.raises(ValueError, match="结局必须是"):
            _fleet_run(conn, outcome=bad, ref=f"fleet:test-fleet/post#x{bad}")


def test_runner_ref_must_look_like_a_fleet_round(conn):
    for bad in ("", "   ", "post-1#round", "extract:m:v"):
        with pytest.raises(ValueError):
            _fleet_run(conn, ref=bad)


def test_unknown_domain_is_refused(conn):
    with pytest.raises(ValueError, match="not found"):
        agent_runs.record_external_run(
            conn, runner_ref="fleet:test-fleet/post-1#1", role="concept",
            domain_key="nope", outcome="ok",
        )


def test_both_origins_show_up_in_the_same_ledger(conn):
    """值班长要在一份台账里同时看到内核与舰队，各自标明来源。"""
    agent_runs.start(conn, role="agent:warden@legal", domain_key="legal")
    _fleet_run(conn)

    rows = agent_runs.list_runs(conn, domain_key="legal")
    origins = {r["origin"] for r in rows}
    assert origins == {"kernel", "fleet"}
    fleet_rows = [r for r in rows if r["origin"] == "fleet"]
    assert fleet_rows and all(r["runner_ref"] for r in fleet_rows)

    summary = agent_runs.summary(conn, domain_key="legal")
    assert summary["by_outcome"].get("ok", 0) >= 1


def test_writeback_does_not_enter_the_quality_ratios(conn):
    """回写的 counts 只进台账；质量比仍从库内内容重算。"""
    from src.bench import quality

    before = quality.all_metrics(conn, namespace="legal", domain_key="legal")
    _fleet_run(conn, counts={"grounding": 999, "evidence": 999})
    after = quality.all_metrics(conn, namespace="legal", domain_key="legal")
    assert before == after


def test_get_by_runner_ref_finds_only_that_round(conn):
    _fleet_run(conn, ref="fleet:test-fleet/post-1#a")
    _fleet_run(conn, ref="fleet:test-fleet/post-1#b")
    got = agent_runs.get_by_runner_ref(conn, runner_ref="fleet:test-fleet/post-1#a")
    assert got is not None and got["runner_ref"].endswith("#a")
    assert agent_runs.get_by_runner_ref(conn, runner_ref="fleet:nope/x#1") is None


# ------------------------------------------------ 并发重试的兜底（不是替代）


def test_the_partial_unique_index_covers_only_external_rows(conn):
    """兜底索引只约束 runner_ref 非空的行：内核岗位的 null 行一行都不受影响。"""
    row = conn.execute(
        "SELECT indexdef FROM pg_indexes "
        "WHERE tablename = 'domain_agent_runs' "
        "AND indexname = 'domain_agent_runs_runner_ref_key'"
    ).fetchone()
    assert row is not None, "缺了兜底索引：并发重试会写出两行「同一轮」"
    assert "UNIQUE" in row["indexdef"]
    assert "runner_ref IS NOT NULL" in row["indexdef"]

    # 内核行（runner_ref 为空）可以有任意多行：空值不参与唯一性，这是刻意的。
    for _ in range(3):
        agent_runs.start(conn, role="agent:warden@legal", domain_key="legal")
    assert conn.execute(
        "SELECT count(*) AS n FROM domain_agent_runs WHERE runner_ref IS NULL"
    ).fetchone()["n"] == 3


def test_a_lost_race_returns_the_winner_instead_of_a_duplicate(conn, monkeypatch):
    """存在性检查漏看时（TOCTOU），第二次插入撞索引 → 回读赢家，不多出一行。

    只让**第一次**检查漏看：那正是竞态的形状（这一瞬间两方都查不到）。若把检查
    整个蒙住，兜底分支的回读也看不到行，测到的就变成「理论上不可达」那条路。
    """
    first, created = _fleet_run(conn)
    assert created is True

    real = agent_runs.get_by_runner_ref
    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return None          # ← 竞态窗口：存在性检查漏看
        return real(*a, **kw)    # ← 兜底分支的回读照常

    monkeypatch.setattr(agent_runs, "get_by_runner_ref", flaky)
    again, created_again = _fleet_run(conn, outcome="failed", counts={"drafts": 99})

    assert created_again is False, "撞了索引也算幂等命中，不能报成新建"
    assert again["id"] == first["id"]
    assert again["outcome"] == "ok", "重放不得改写已记录的结局"
    n = conn.execute(
        "SELECT count(*) AS n FROM domain_agent_runs WHERE runner_ref = %s",
        ("fleet:test-fleet/post-1#2026-11-13",),
    ).fetchone()["n"]
    assert n == 1, "同一轮只能有一行"
