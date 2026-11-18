"""工作单的类型化指派人、认领与完成（add-fleet-execution-loop §1）。

三个决定在这里被钉住：

- **指派人三档**（人 / 内核岗位 / 舰队），``assignee`` 只作人读展示名——授权读的
  是 ``assignee_kind`` + ``assignee_ref``。混用一列时，同名不同身份的人会拿到别人
  的工单。
- **认领排他**靠 UPDATE 的 ``WHERE status='pending'`` 与影响行数，不做先查后改：
  先查后改在并发下两边都会读到 pending，然后都成功。
- **完成不写知识单元**：工单只表达「这件事做完了」，内容仍走提案或内核写入路径。
"""

from __future__ import annotations

import pytest

from src.bench import authoring, dispatch, estate, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from tests._fleet_fixtures import register_fleet


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    from src.eval.store import ensure_schema

    # rubrics/criteria come from the legacy seed, not ensure_schema; the estate
    # matrix reads them, so build the deployed shape (same as the other modules
    # that exercise estate).
    empty_db.execute(
        "CREATE TABLE IF NOT EXISTS rubrics (id BIGINT GENERATED ALWAYS AS IDENTITY "
        "PRIMARY KEY, name TEXT NOT NULL, context TEXT, source TEXT, source_path TEXT, "
        "description TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    empty_db.commit()
    from src.eval import store as eval_store

    eval_store._ensured_dbs.clear()
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


def _domain(conn):
    return workspaces.get_domain(conn, domain_key="legal")


def _rows(conn):
    return estate.matrix(conn, domains=[_domain(conn)])


def _task(conn, **kw):
    params = dict(
        domain_id=_domain(conn)["id"], assignee="alice", title="t", detail="d",
        target_kind="estate-gap", target_key="ontology", created_by="lead",
    )
    params.update(kw)
    return authoring.authoring_create_task(conn, **params)


# ------------------------------------------------------------------ routing


def test_route_table_is_total_and_refuses_strangers():
    for gap in dispatch.GAP_TASKS:
        assert dispatch.route_for(gap) in (
            dispatch.HUMAN_ROUTE, dispatch.FLEET_ROUTE
        ) or dispatch.route_for(gap).startswith(dispatch.KERNEL_PREFIX)

    with pytest.raises(ValueError, match="unknown pillar"):
        dispatch.route_for("no-such-gap")


def test_gap_owner_is_derived_from_the_route_table():
    """团队岗的归属表与分诊表必须同源，否则两份会漂移。"""
    from src.bench import team_roles

    assert team_roles.GAP_OWNER == {
        gap: dispatch.kernel_role_for(gap) for gap in dispatch.GAP_TASKS
    }
    assert team_roles.GAP_OWNER["quality:review_lag"] is None, "复核积压归人"
    assert team_roles.GAP_OWNER["ontology"] == "builder"


def test_review_backlog_is_never_dispatched_to_an_agent(conn):
    """归人的缺口不创建任何智能体工单。"""
    out = dispatch.dispatch(
        conn, rows=_rows(conn), gap="quality:review_lag", assignee="agent:warden@legal",
        created_by="lead", assignee_kind="kernel-role", assignee_ref="warden",
    )
    assert out["route"] == dispatch.HUMAN_ROUTE
    assert conn.execute("SELECT count(*) AS n FROM authoring_tasks").fetchone()["n"] == 0


def test_kernel_gap_cannot_be_assigned_to_a_different_role(conn):
    with pytest.raises(ValueError, match="由内核岗位"):
        dispatch.dispatch(
            conn, rows=_rows(conn), gap="ontology", assignee="agent:scout@legal",
            created_by="lead", assignee_kind="kernel-role", assignee_ref="scout",
        )


# -------------------------------------------------------------- assignee kinds


def test_human_assignee_is_projected_as_human(conn):
    task = _task(conn, assignee="alice@example.com")
    assert task["assignee_kind"] == "human"
    assert task["assignee_ref"] is None


def test_kernel_role_assignee_carries_the_role(conn):
    task = _task(conn, assignee="agent:builder@legal", assignee_kind="kernel-role",
                 assignee_ref="builder")
    assert task["assignee_kind"] == "kernel-role"
    assert task["assignee_ref"] == "builder"


def test_fleet_assignee_must_resolve_to_a_live_registration(conn):
    with pytest.raises(ValueError, match="不是本域可用的舰队登记"):
        _task(conn, assignee="fleet-x", assignee_kind="fleet", assignee_ref="fleet_x")

    register_fleet(conn, "fleet_x", ["legal"])
    task = _task(conn, assignee="fleet-x", assignee_kind="fleet", assignee_ref="fleet_x")
    assert task["assignee_kind"] == "fleet" and task["assignee_ref"] == "fleet_x"


def test_fleet_registered_for_another_domain_is_refused(conn):
    register_fleet(conn, "fleet_other", ["gov"])
    with pytest.raises(ValueError, match="domain_mismatch"):
        _task(conn, assignee="f", assignee_kind="fleet", assignee_ref="fleet_other")


def test_fleet_assignee_without_ref_is_refused(conn):
    with pytest.raises(ValueError, match="requires an assignee_ref"):
        _task(conn, assignee="f", assignee_kind="fleet")


def test_unknown_assignee_kind_is_refused(conn):
    with pytest.raises(ValueError, match="assignee_kind must be one of"):
        _task(conn, assignee="x", assignee_kind="robot")


# ------------------------------------------------------------------- claim


def test_claim_moves_pending_to_in_progress(conn):
    task = _task(conn)
    claimed = authoring.authoring_claim_task(conn, task_id=task["id"], actor="fleet:a/1")
    assert claimed["status"] == "in_progress"
    assert claimed["transitions"][-1]["by"] == "fleet:a/1"
    assert claimed["transitions"][-1]["from"] == "pending"


def test_a_second_claim_is_refused_rather_than_duplicated(conn):
    task = _task(conn)
    authoring.authoring_claim_task(conn, task_id=task["id"], actor="fleet:a/1")
    with pytest.raises(authoring.TaskAlreadyClaimed, match="已被认领"):
        authoring.authoring_claim_task(conn, task_id=task["id"], actor="fleet:b/2")

    rows = conn.execute(
        "SELECT transitions FROM authoring_tasks WHERE id = %s", (task["id"],)
    ).fetchone()
    claims = [e for e in rows["transitions"] if e["to"] == "in_progress"]
    assert len(claims) == 1, "只应留一条认领记录"


def test_claiming_a_missing_task_names_the_id(conn):
    with pytest.raises(ValueError, match="not found"):
        authoring.authoring_claim_task(conn, task_id=999999, actor="fleet:a/1")


def test_claim_is_atomic_under_concurrency(conn):
    """并发认领只能有一个赢家——靠 UPDATE 的 WHERE 与影响行数，不靠先查后改。"""
    task = _task(conn)
    won, lost = 0, 0
    for actor in ("fleet:a/1", "fleet:b/2", "fleet:a/1"):
        try:
            authoring.authoring_claim_task(conn, task_id=task["id"], actor=actor)
            won += 1
        except authoring.TaskAlreadyClaimed:
            lost += 1
    assert (won, lost) == (1, 2)


# ---------------------------------------------------------------- complete


def test_complete_requires_a_claim_first(conn):
    task = _task(conn)
    with pytest.raises(ValueError, match="必须先认领"):
        authoring.authoring_complete_task(conn, task_id=task["id"], actor="fleet:a/1")


def test_complete_records_artifacts_and_note_in_the_trail(conn):
    task = _task(conn)
    authoring.authoring_claim_task(conn, task_id=task["id"], actor="fleet:a/1")
    done = authoring.authoring_complete_task(
        conn, task_id=task["id"], actor="fleet:a/1",
        artifact_refs=[{"proposal_id": 7}], note="产出 3 条草案",
    )
    assert done["status"] == "done"
    last = done["transitions"][-1]
    assert last["from"] == "in_progress" and last["to"] == "done"
    assert last["artifacts"] == [{"proposal_id": 7}]
    assert last["note"] == "产出 3 条草案"


def test_complete_twice_is_refused(conn):
    task = _task(conn)
    authoring.authoring_claim_task(conn, task_id=task["id"], actor="fleet:a/1")
    authoring.authoring_complete_task(conn, task_id=task["id"], actor="fleet:a/1")
    with pytest.raises(ValueError, match="必须先认领"):
        authoring.authoring_complete_task(conn, task_id=task["id"], actor="fleet:a/1")


def test_completing_does_not_write_knowledge_units(conn):
    task = _task(conn)
    authoring.authoring_claim_task(conn, task_id=task["id"], actor="fleet:a/1")
    before = conn.execute("SELECT count(*) AS n FROM knowledge_units").fetchone()["n"]
    authoring.authoring_complete_task(conn, task_id=task["id"], actor="fleet:a/1")
    after = conn.execute("SELECT count(*) AS n FROM knowledge_units").fetchone()["n"]
    assert before == after
