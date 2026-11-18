"""运行回执的两个读面（add-fleet-execution-loop §3.5）。

回写面写了行，但**回写方怎么知道它落库了**？团队页面能给人看，机器看不见。所以
两个入口，一条隔离判据（``submitters.may_read_runner_ref``）：

- 会话面 ``GET /api/d/{domain_key}/runs``：域成员读整份台账（页面本来就能看到，
  读面不该比页面更严或更松），非成员 403。
- 机器面 ``GET /api/v1/distribution/{domain_key}/runs``：沿用拉取面那枚
  ``X-Consumer-Token``，但**只有 fleet 种类**能读，且只能读
  ``fleet:<自己的 fleet_ref>/`` 开头的轮次。

三条会让这个面变成谎话的写法，都在这里挡住：把别人的前缀当成空结果返回（看起来
像「我的回写没落」）、让 machine 种类消费者读运行（它不是提交方）、把
``fleet_ref`` 当成子串比（``fleet:f1x`` 会被 ``f1`` 的登记读到）。
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.bench import agent_runs, distribution, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user
from src.web.deps import get_db

DOMAIN = "legal"
TOKEN = "fleet-token-plaintext"


@pytest.fixture()
def world(seeded_db):  # noqa: F811 - provided by tests/conftest.py
    # 用 seeded_db 而不是 empty_db：empty_db 每个测试建一个库并在收尾 DROP，而
    # create_app() 起的连接仍挂在该库上，DROP 会撞 ObjectInUse。Web 测试一律用
    # 会话库 + 逐测试 TRUNCATE，这里跟随同一约定。
    empty_db = seeded_db
    schema = {
        "entity_types": ["company"],
        "concept_structures": {},
        "relationship_kinds": ["belongs_to"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {},
    }
    templates.create_template(conn=empty_db, name="tpl", schema=schema, created_by="t")
    domain = workspaces.instantiate_domain(
        conn=empty_db, key=DOMAIN, name="法律域", template_name="tpl",
        template_version=None, created_by="t",
    )
    workspaces.add_member(
        conn=empty_db, domain_id=domain["id"], user_id="lara", role="lead", added_by="t"
    )
    distribution.register_consumer(
        empty_db, name="ontology-fleet", domains=[DOMAIN],
        token_hash=hashlib.sha256(TOKEN.encode()).hexdigest(), created_by="t",
        kind="fleet", fleet_ref="fleet_a",
    )
    distribution.register_consumer(
        empty_db, name="fd-wire", domains=[DOMAIN],
        token_hash=hashlib.sha256(b"machine-token").hexdigest(), created_by="t",
        kind="machine",
    )
    yield empty_db


@pytest.fixture(autouse=True)
def _no_idp(monkeypatch):
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)


def _machine(db) -> TestClient:
    """No identity override: the machine surface must work without a session."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _session(db, sub: str) -> TestClient:
    app = create_app()
    user = User(sub=sub, name=sub, email=f"{sub}@example.com",
                scopes=["content:read"], channel="test")

    def _current(request: Request) -> User:
        request.state.user = user
        return user

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _current
    return TestClient(app)


def _run(db, ref: str, outcome: str = "ok"):
    return agent_runs.record_external_run(
        db, runner_ref=ref, role="concept", domain_key=DOMAIN, outcome=outcome,
        counts={"drafts": 1},
    )[0]


# ------------------------------------------------------------------ machine


def test_a_fleet_reads_back_its_own_round(world):
    _run(world, "fleet:fleet_a/post_1#1")
    with _machine(world) as c:
        r = c.get(f"/api/v1/distribution/{DOMAIN}/runs",
                  headers={"X-Consumer-Token": TOKEN})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fleet_ref"] == "fleet_a"
    assert body["count"] == 1
    assert body["runs"][0]["runner_ref"] == "fleet:fleet_a/post_1#1"
    assert body["runs"][0]["origin"] == "fleet"


def test_asking_for_another_fleets_round_is_403_not_empty(world):
    """空结果会被读成「我的回写没落库」——那是错误的事实。"""
    _run(world, "fleet:fleet_b/post_1#1")
    with _machine(world) as c:
        r = c.get(f"/api/v1/distribution/{DOMAIN}/runs",
                  params={"runner_ref": "fleet:fleet_b/post_1#1"},
                  headers={"X-Consumer-Token": TOKEN})
    assert r.status_code == 403
    assert "不属于 fleet_a" in r.json()["detail"]


def test_a_fleet_ref_is_matched_by_prefix_boundary_not_substring(world):
    """``fleet:<ref>`` 必须是**开头**，不是「出现在某处」。

    判据用 query 参数构造：库里的 runner_ref 都被写入期校验过，只有查询参数能携带
    任意形状。一个舰队把自己的 ref 拼在别人后面（或反过来）不该读到任何东西。
    """
    _run(world, "fleet:fleet_a/post_1#1")
    with _machine(world) as c:
        sneaky = c.get(
            f"/api/v1/distribution/{DOMAIN}/runs",
            params={"runner_ref": "x fleet:fleet_a/post_1#1"},
            headers={"X-Consumer-Token": TOKEN},
        )
        other = c.get(
            f"/api/v1/distribution/{DOMAIN}/runs",
            params={"runner_ref": "fleet:fleet_ab/post_1#1"},
            headers={"X-Consumer-Token": TOKEN},
        )
    assert sneaky.status_code == 403
    assert other.status_code == 403


def test_without_runner_ref_only_own_rounds_come_back(world):
    _run(world, "fleet:fleet_a/post_1#1")
    _run(world, "fleet:fleet_b/post_2#1")
    agent_runs.start(world, role="agent:warden@legal", domain_key=DOMAIN)
    with _machine(world) as c:
        r = c.get(f"/api/v1/distribution/{DOMAIN}/runs",
                  headers={"X-Consumer-Token": TOKEN})
    refs = [row["runner_ref"] for row in r.json()["runs"]]
    assert refs == ["fleet:fleet_a/post_1#1"]


def test_a_plain_machine_consumer_may_not_read_runs(world):
    with _machine(world) as c:
        r = c.get(f"/api/v1/distribution/{DOMAIN}/runs",
                  headers={"X-Consumer-Token": "machine-token"})
    assert r.status_code == 403
    assert "不是 fleet 种类" in r.json()["detail"]


def test_machine_face_keeps_the_three_state_token_check(world):
    url = f"/api/v1/distribution/{DOMAIN}/runs"
    with _machine(world) as c:
        missing = c.get(url)
        unknown = c.get(url, headers={"X-Consumer-Token": "nope"})
        other_domain = c.get("/api/v1/distribution/gov/runs",
                             headers={"X-Consumer-Token": TOKEN})
    assert missing.status_code == 401
    assert unknown.status_code == 403
    assert other_domain.status_code == 403
    assert "该域不在绑定范围" in other_domain.json()["detail"]


def test_a_revoked_token_cannot_read_back(world):
    distribution.revoke_consumer(world, name="ontology-fleet")
    with _machine(world) as c:
        r = c.get(f"/api/v1/distribution/{DOMAIN}/runs",
                  headers={"X-Consumer-Token": TOKEN})
    assert r.status_code == 403
    assert "吊销" in r.json()["detail"]


# ------------------------------------------------------------------ session


def test_a_domain_member_sees_the_whole_ledger(world):
    _run(world, "fleet:fleet_a/post_1#1")
    agent_runs.start(world, role="agent:warden@legal", domain_key=DOMAIN)
    with _session(world, "lara") as c:
        r = c.get(f"/api/d/{DOMAIN}/runs")
    assert r.status_code == 200, r.text
    origins = {row["origin"] for row in r.json()["runs"]}
    assert origins == {"fleet", "kernel"}


def test_a_non_member_is_refused_without_leaking_the_domain(world):
    with _session(world, "bob") as c:
        r = c.get(f"/api/d/{DOMAIN}/runs")
    assert r.status_code == 403


def test_unknown_domain_is_404_before_any_read(world):
    with _session(world, "lara") as c:
        r = c.get("/api/d/nope/runs")
    assert r.status_code == 404


def test_origin_filter_splits_the_two_kinds(world):
    _run(world, "fleet:fleet_a/post_1#1")
    agent_runs.start(world, role="agent:warden@legal", domain_key=DOMAIN)
    with _session(world, "lara") as c:
        fleet_only = c.get(f"/api/d/{DOMAIN}/runs", params={"origin": "fleet"})
    assert [row["origin"] for row in fleet_only.json()["runs"]] == ["fleet"]
