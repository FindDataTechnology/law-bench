"""值班长视图：质量比 + 运行台账 + 按批待确认，一页看全。

这一页的规矩是"同屏但不同权"：

- 数字全部来自库（`quality.all_metrics`、`agent_runs.summary`、`proposals.batches`），
  页面自己不算任何指标；
- 只读身份看不到确认/退回按钮，且按钮指向的批量端点自己还有 lead 闸——
  看得见不代表点得动；
- 未声明岗位参数的线如实说"未声明"，不显示一个空的运行列表糊过去。
"""

from __future__ import annotations

import re

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

import packs.legal  # noqa: F401 — 归名规则与 web 边缘一致
from src.bench import agent_runs, authoring, proposals, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema
from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user
from src.web.deps import get_db

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
    # 评测柱读 rubrics；它来自遗留 seed，不在 ensure_schema 里
    empty_db.execute(
        "CREATE TABLE IF NOT EXISTS rubrics (id BIGINT GENERATED ALWAYS AS IDENTITY "
        "PRIMARY KEY, name TEXT NOT NULL, context TEXT, source TEXT, source_path TEXT, "
        "description TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    empty_db.commit()
    from src.eval import store as eval_store
    eval_store._ensured_dbs.clear()
    ensure_schema(db_path=empty_db)
    templates.create_template(conn=empty_db, name="tpl", schema=dict(SCHEMA), created_by="t")
    dom = workspaces.instantiate_domain(
        conn=empty_db, key="legal", name="法律域", template_name="tpl",
        template_version=None, created_by="t",
    )
    for role, sub in (("lead", "u-lead"), ("expert", "u-expert"), ("annotator", "u-read")):
        workspaces.add_member(conn=empty_db, domain_id=dom["id"], user_id=sub, role=role,
                              added_by="t")
    empty_db.commit()
    # add-fleet-execution-loop: fleet: sources now need a live registration.
    from _fleet_fixtures import provision_default_fleet_world
    provision_default_fleet_world(empty_db)
    yield empty_db
    from src.eval.db import close_shared_conn
    close_shared_conn()


def _client(db, sub: str) -> TestClient:
    app = create_app()
    user = User(sub=sub, name=sub, email=f"{sub}@e.com",
                scopes=["content:read", "content:write"], channel="test")

    def _cu(request: Request) -> User:
        request.state.user = user
        return user

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _cu
    return TestClient(app)


def _body(html: str) -> str:
    i = html.find("<body")
    body = html[i:] if i >= 0 else html
    return re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.S)


@pytest.fixture(autouse=True)
def _no_idp(monkeypatch):
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)


def test_the_page_shows_all_six_ratios(conn):
    authoring.authoring_create_unit(conn, domain_key="legal", kind="concept",
                                    external_key="违约金调整", body="b", operator="t",
                                    attrs={"chunk_id": "c1"})
    with _client(conn, "u-read") as c:
        page = _body(c.get("/d/legal/team").text)
    for name in ("grounding", "evidence", "referential", "review_lag",
                 "key_hygiene", "judge"):
        assert name in page, f"{name} 未出现在值班页"


def test_a_metric_with_no_denominator_says_so_instead_of_zero(conn):
    with _client(conn, "u-read") as c:
        page = _body(c.get("/d/legal/team").text)
    assert "无物可算" in page


def test_the_ledger_section_renders_counts_and_outcome(conn):
    run = agent_runs.start(conn, role="agent:warden@legal", domain_key="legal")
    agent_runs.finish(conn, run_id=run["id"], outcome="thin",
                      counts={"gap_count": 3}, detail="三个缺口")
    with _client(conn, "u-read") as c:
        page = _body(c.get("/d/legal/team").text)
    assert "agent:warden@legal" in page
    assert "thin" in page
    assert "三个缺口" in page


def test_pending_batches_are_listed_with_actions_for_writers(conn):
    proposals.submit(conn, domain_key="legal", source="fleet:a/1", kind="concept",
                     external_key="违约金调整", body="b",
                     evidence={"quote": "q", "batch": "b-1", "usable_rate": 0.75},
                     submitted_by="fleet:a/1")
    with _client(conn, "u-expert") as c:
        page = _body(c.get("/d/legal/team").text)
    assert "b-1" in page
    assert "整批确认" in page and "整批退回" in page


def test_a_reader_sees_the_numbers_but_no_write_buttons(conn):
    proposals.submit(conn, domain_key="legal", source="fleet:a/1", kind="concept",
                     external_key="违约金调整", body="b",
                     evidence={"quote": "q", "batch": "b-1"}, submitted_by="fleet:a/1")
    with _client(conn, "u-read") as c:
        page = _body(c.get("/d/legal/team").text)
    assert "b-1" in page                 # 数字照看
    assert "整批确认" not in page         # 按钮不给
    assert "确认需要 lead 权限" in page


def test_batch_confirm_actually_writes_through_the_kernel(conn):
    p = proposals.submit(conn, domain_key="legal", source="fleet:a/1", kind="concept",
                         external_key="违约金调整", body="b",
                         evidence={"quote": "q", "batch": "b-1"}, submitted_by="fleet:a/1")
    with _client(conn, "u-lead") as c:
        c.post("/d/legal/inbox/batch", data={"batch": "b-1", "action": "confirm"},
               follow_redirects=False)
    assert conn.execute("SELECT state FROM domain_proposals WHERE id = %s",
                        (p["id"],)).fetchone()["state"] == "confirmed"
    assert authoring.authoring_get_unit(conn, domain_key="legal", kind="concept",
                                        external_key="违约金调整") is not None


def test_the_declared_plan_is_shown(conn):
    with _client(conn, "u-read") as c:
        page = _body(c.get("/d/legal/team").text)
    # legal 的 pack 声明了 warden/verifier/scout/builder/concept，未声明 eval/release
    assert "warden" in page and "concept" in page
