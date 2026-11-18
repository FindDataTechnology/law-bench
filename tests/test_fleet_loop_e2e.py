"""一条闭环，全程走真实 HTTP（add-fleet-execution-loop §7.1 / §6.4 的离线那半）。

审定过的判据是「缺口 → 工单 → 舰队认领 → 执行 → 运行回写 → 产物入箱 → 确认 → 结果
可见」。这条测试就走这一串，**不调内核函数**（除了造世界）：任何一处接线缺失，链路
就断在一个具体的状态码上。

为什么值得写成一整条而不是八个单测：每一段单独绿的时候，缝里可能根本没接上——工单
派得出去但没人能认领、回写落库了但读不回来、提案进了箱但确认路径不认这个来源。这些
都只在**串联**的时候才现形。

身份：舰队用 `X-Consumer-Token`（机器，无会话），域负责人用会话身份。两者是不同的
闸，混用就等于没测。
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.bench import distribution, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user
from src.web.deps import get_db

CLIENT_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "fleet_client.py"


def _load_fleet_client():
    spec = importlib.util.spec_from_file_location("fleet_client_under_test", CLIENT_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

DOMAIN = "loop-domain"
TOKEN = "loop-fleet-token"
FLEET_REF = "fleet_loop"


@pytest.fixture()
def world(seeded_db):  # noqa: F811 - provided by tests/conftest.py
    conn = seeded_db
    schema = {
        "entity_types": ["company"],
        "concept_structures": {},
        "relationship_kinds": ["belongs_to"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {},
    }
    templates.create_template(conn, name="loop-tpl", schema=schema, created_by="seed")
    domain = workspaces.instantiate_domain(
        conn, key=DOMAIN, name="闭环域", template_name="loop-tpl",
        template_version=None, created_by="seed",
    )
    workspaces.add_member(
        conn, domain_id=domain["id"], user_id="lara", role="lead", added_by="seed"
    )
    # 舰队这一侧**不是一个人**：它只持有一枚 token，没有会话，也没有成员身份。
    # 提交走机器面（源必须是自己那条登记的前缀），复核才有会话身份——自提自确认
    # 在这里不是靠「两个人」绕过去的，而是机制上做不到（token 没有确认入口）。
    distribution.register_consumer(
        conn, name="loop-fleet", domains=[DOMAIN],
        token_hash=hashlib.sha256(TOKEN.encode()).hexdigest(), created_by="seed",
        kind="fleet", fleet_ref=FLEET_REF,
    )
    yield conn


@pytest.fixture(autouse=True)
def _no_idp(monkeypatch):
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)


def _machine(db) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _human(db, sub: str = "lara") -> TestClient:
    app = create_app()
    user = User(sub=sub, name=sub, email=f"{sub}@example.com",
                scopes=["content:read", "content:write"], channel="test")

    def _current(request: Request) -> User:
        request.state.user = user
        return user

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _current
    return TestClient(app)


def _machine_headers():
    return {"X-Consumer-Token": TOKEN}


def test_the_whole_loop_over_http(world):
    conn = world

    # ① 缺口存在：本域还没有自己的知识单元（estate 判据与派单同源）。
    from src.bench import estate

    domain = workspaces.get_domain(conn, domain_key=DOMAIN)
    rows = estate.matrix(conn, domains=[domain])
    assert "ontology" in rows[0]["gaps"], "闭环应从「真的有缺口」开始"

    # ② 派单给舰队（会话身份：lead）。走真实表单端点。
    with _human(conn) as h:
        dispatched = h.post(
            "/d/dispatch",
            data={
                "gap": "ontology", "assignee": "loop-fleet",
                "assignee_kind": "fleet", "assignee_ref": FLEET_REF,
            },
            follow_redirects=False,
        )
    assert dispatched.status_code == 303, dispatched.text

    task = conn.execute(
        "SELECT id, assignee_kind, assignee_ref, status FROM authoring_tasks "
        "WHERE target_key = 'ontology'"
    ).fetchone()
    assert (task["assignee_kind"], task["assignee_ref"], task["status"]) == (
        "fleet", FLEET_REF, "pending",
    )

    # ③ 舰队领单（机器身份，无会话）。别人认领不了它。
    with _machine(conn) as m:
        claimed = m.post(
            f"/api/v1/distribution/{DOMAIN}/work-orders/{task['id']}/claim",
            headers=_machine_headers(),
        )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["task"]["status"] == "in_progress"

    # 自己的重试是幂等命中（200 + created:false）：机器端点会被网络重试，
    # 把「已经做过了」报成冲突，等于让健康的舰队去重试它治不好的错。
    with _machine(conn) as m:
        again = m.post(
            f"/api/v1/distribution/{DOMAIN}/work-orders/{task['id']}/claim",
            headers=_machine_headers(),
        )
    assert again.status_code == 200, again.text
    assert again.json()["created"] is False
    claims = [
        e for e in again.json()["task"]["transitions"] if e.get("to") == "in_progress"
    ]
    assert len(claims) == 1, "重试不得再落一条认领事件"

    # ④ 执行完回写这一轮（机器身份，幂等）。
    runner_ref = f"fleet:{FLEET_REF}/post_ontology#1"
    with _machine(conn) as m:
        wrote = m.post(
            f"/api/v1/distribution/{DOMAIN}/runs",
            json={
                "runner_ref": runner_ref, "role": "concept", "outcome": "ok",
                "counts": {"drafts": 2}, "task_id": task["id"],
            },
            headers=_machine_headers(),
        )
    assert wrote.status_code == 200, wrote.text
    assert wrote.json()["created"] is True

    with _machine(conn) as m:
        replay = m.post(
            f"/api/v1/distribution/{DOMAIN}/runs",
            json={"runner_ref": runner_ref, "role": "concept", "outcome": "failed"},
            headers=_machine_headers(),
        )
        readback = m.get(
            f"/api/v1/distribution/{DOMAIN}/runs",
            params={"runner_ref": runner_ref}, headers=_machine_headers(),
        )
    assert replay.json()["created"] is False
    assert replay.json()["run"]["outcome"] == "ok", "重放不得改写已记录的结局"
    assert readback.json()["count"] == 1

    # ⑤ 产物入箱：**舰队用自己那枚 token 提交**，全程没有会话。
    # 这一步最初只能借一个服务账号的会话，于是「闭环」在最后一格上要求一个人——
    # 而那正是 D7 拒绝的形态（舰队持有一个能代表人的凭据）。现在提交走机器面，
    # 提交方是登记引用本身，`svc-fleet` 这个服务身份在这里不再需要。
    with _machine(conn) as m:
        submitted = m.post(
            f"/api/v1/distribution/{DOMAIN}/proposals",
            json={
                "source": f"fleet:{FLEET_REF}/post_ontology",
                "kind": "company", "external_key": "loop-corp",
                "body": "闭环域的第一家主体", "evidence": {"url": "https://e.test/1"},
            },
            headers=_machine_headers(),
        )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["created"] is True

    # 网络重试是幂等命中，而不是第二份产物。
    with _machine(conn) as m:
        again = m.post(
            f"/api/v1/distribution/{DOMAIN}/proposals",
            json={
                "source": f"fleet:{FLEET_REF}/post_ontology",
                "kind": "company", "external_key": "loop-corp",
                "body": "闭环域的第一家主体", "evidence": {"url": "https://e.test/1"},
            },
            headers=_machine_headers(),
        )
    assert again.status_code == 200, again.text
    assert again.json()["created"] is False
    assert again.json()["id"] == submitted.json()["id"]

    # ⑥ 域负责人确认 → 知识单元落库。
    with _human(conn) as h:
        confirmed = h.post(
            f"/d/{DOMAIN}/inbox/{submitted.json()['id']}/confirm",
            follow_redirects=False,
        )
    assert confirmed.status_code == 303, confirmed.text
    assert "err=1" not in confirmed.headers["location"], confirmed.headers["location"]

    unit = conn.execute(
        "SELECT count(*) AS n FROM knowledge_units WHERE external_key = 'loop-corp'"
    ).fetchone()
    assert unit["n"] == 1, "确认后单元必须真的出现在库里"

    # ⑦ 缺口消失 + 结果对提交方可见（同一个域，四份证据都在）。
    rows_after = estate.matrix(conn, domains=[workspaces.get_domain(conn, domain_key=DOMAIN)])
    assert "ontology" not in rows_after[0]["gaps"], "闭环走完，缺口应当消失"

    # 结果对提交方可见——舰队读自己的结局，同样只用 token。
    with _machine(conn) as m:
        outcomes = m.get(
            f"/api/v1/distribution/{DOMAIN}/proposals/outcomes",
            params={"source": f"fleet:{FLEET_REF}/post_ontology"},
            headers=_machine_headers(),
        )
    assert outcomes.status_code == 200, outcomes.text
    assert outcomes.json()["outcomes"][0]["state"] == "confirmed"

    # ⑧ 舰队关单（机器身份）。
    with _machine(conn) as m:
        done = m.post(
            f"/api/v1/distribution/{DOMAIN}/work-orders/{task['id']}/complete",
            json={"note": "产出 2 条草案", "artifact_refs": [{"proposal_id": submitted.json()["id"]}]},
            headers=_machine_headers(),
        )
    assert done.status_code == 200, done.text
    assert done.json()["task"]["status"] == "done"

    # 四份证据一起核对：工单、运行、提案、单元。
    assert conn.execute(
        "SELECT count(*) AS n FROM authoring_tasks WHERE status = 'done'"
    ).fetchone()["n"] == 1
    assert conn.execute(
        "SELECT count(*) AS n FROM domain_agent_runs WHERE runner_ref = %s", (runner_ref,)
    ).fetchone()["n"] == 1
    assert conn.execute(
        "SELECT count(*) AS n FROM domain_proposals WHERE state = 'confirmed'"
    ).fetchone()["n"] == 1


def test_another_fleet_cannot_claim_or_close_the_task(world):
    """派给 A 的工单，B 认领不了；显示名相同也不行——授权读的是登记引用。"""
    conn = world
    domain = workspaces.get_domain(conn, domain_key=DOMAIN)
    from src.bench import authoring

    task = authoring.authoring_create_task(
        conn, domain_id=domain["id"], assignee="loop-fleet", title="t", detail="d",
        target_kind="estate-gap", target_key="ontology", created_by="lara",
        assignee_kind="fleet", assignee_ref=FLEET_REF,
    )
    distribution.register_consumer(
        conn, name="other-fleet", domains=[DOMAIN],
        token_hash=hashlib.sha256(b"other").hexdigest(), created_by="seed",
        kind="fleet", fleet_ref="fleet_other",
    )
    with _machine(conn) as m:
        stolen = m.post(
            f"/api/v1/distribution/{DOMAIN}/work-orders/{task['id']}/claim",
            headers={"X-Consumer-Token": "other"},
        )
    assert stolen.status_code == 403
    assert "不是派给舰队" in stolen.json()["detail"]


def test_the_machine_surface_still_refuses_a_plain_machine_consumer(world):
    conn = world
    distribution.register_consumer(
        conn, name="plain-reader", domains=[DOMAIN],
        token_hash=hashlib.sha256(b"reader").hexdigest(), created_by="seed",
        kind="machine",
    )
    domain = workspaces.get_domain(conn, domain_key=DOMAIN)
    from src.bench import authoring

    task = authoring.authoring_create_task(
        conn, domain_id=domain["id"], assignee="loop-fleet", title="t", detail="d",
        target_kind="estate-gap", target_key="ontology", created_by="lara",
        assignee_kind="fleet", assignee_ref=FLEET_REF,
    )
    with _machine(conn) as m:
        r = m.post(
            f"/api/v1/distribution/{DOMAIN}/work-orders/{task['id']}/claim",
            headers={"X-Consumer-Token": "reader"},
        )
    assert r.status_code == 403
    assert "不是 fleet 种类" in r.json()["detail"]


def test_a_fleet_cannot_write_back_a_round_under_another_fleets_ref(world):
    with _machine(world) as m:
        r = m.post(
            f"/api/v1/distribution/{DOMAIN}/runs",
            json={"runner_ref": "fleet:fleet_other/post_1#1", "role": "concept",
                  "outcome": "ok"},
            headers=_machine_headers(),
        )
    assert r.status_code == 403
    assert "runner_ref 必须形如" in r.json()["detail"]


def test_outcome_outside_the_vocabulary_is_422_not_a_row(world):
    with _machine(world) as m:
        r = m.post(
            f"/api/v1/distribution/{DOMAIN}/runs",
            json={"runner_ref": f"fleet:{FLEET_REF}/p#9", "role": "concept",
                  "outcome": "perfect"},
            headers=_machine_headers(),
        )
    assert r.status_code == 422
    assert "结局必须是" in r.json()["detail"]
    assert world.execute(
        "SELECT count(*) AS n FROM domain_agent_runs WHERE origin = 'fleet'"
    ).fetchone()["n"] == 0


def test_writeback_without_a_role_is_refused(world):
    """台账第一列是岗位；允许空岗位，「谁在跑」就永久缺一角。"""
    with _machine(world) as m:
        r = m.post(
            f"/api/v1/distribution/{DOMAIN}/runs",
            json={"runner_ref": f"fleet:{FLEET_REF}/p#1", "outcome": "ok"},
            headers=_machine_headers(),
        )
    assert r.status_code == 422
    assert "role 不能为空" in r.json()["detail"]


def test_writeback_cannot_reference_a_task_outside_the_domain(world):
    conn = world
    other = workspaces.instantiate_domain(
        conn, key="other-domain", name="别域", template_name="loop-tpl",
        template_version=None, created_by="seed",
    )
    # 别域的那张单派给别域的舰队：本域舰队在那边根本不是可用登记，创建期就会被
    # 拒——所以要造出「跨域 task_id」这个局面，得让别域自有一支舰队。
    other_ref = "fleet_other_domain"
    distribution.register_consumer(
        conn, name="other-domain-fleet", domains=["other-domain"],
        token_hash=hashlib.sha256(b"other-domain-token").hexdigest(), created_by="seed",
        kind="fleet", fleet_ref=other_ref,
    )
    from src.bench import authoring

    foreign = authoring.authoring_create_task(
        conn, domain_id=other["id"], assignee="other-domain-fleet", title="t", detail="d",
        target_kind="estate-gap", target_key="ontology", created_by="lara",
        assignee_kind="fleet", assignee_ref=other_ref,
    )
    with _machine(conn) as m:
        r = m.post(
            f"/api/v1/distribution/{DOMAIN}/runs",
            json={"runner_ref": f"fleet:{FLEET_REF}/p#1", "role": "concept",
                  "outcome": "ok", "task_id": foreign["id"]},
            headers=_machine_headers(),
        )
    assert r.status_code == 404, r.text


def test_a_malformed_completion_body_is_422_not_a_silent_note(world):
    """空体可以关单；**写坏的 JSON 不行**——当成空体处理，舰队会以为 note 记上了。"""
    conn = world
    domain = workspaces.get_domain(conn, domain_key=DOMAIN)
    from src.bench import authoring

    task = authoring.authoring_create_task(
        conn, domain_id=domain["id"], assignee="loop-fleet", title="t", detail="d",
        target_kind="estate-gap", target_key="ontology", created_by="lara",
        assignee_kind="fleet", assignee_ref=FLEET_REF,
    )
    with _machine(conn) as m:
        m.post(f"/api/v1/distribution/{DOMAIN}/work-orders/{task['id']}/claim",
               headers=_machine_headers())
        bad = m.post(
            f"/api/v1/distribution/{DOMAIN}/work-orders/{task['id']}/complete",
            content='{"note": "少了右括号"'.encode("utf-8"),
            headers={**_machine_headers(), "Content-Type": "application/json"},
        )
        empty = m.post(
            f"/api/v1/distribution/{DOMAIN}/work-orders/{task['id']}/complete",
            headers=_machine_headers(),
        )
    assert bad.status_code == 422
    assert "JSON 对象" in bad.json()["detail"]
    assert empty.status_code == 200, empty.text
    assert empty.json()["task"]["status"] == "done"


def test_a_non_integer_task_id_is_422_not_a_500(world):
    """形状错误要是 422：冒成 500 就读起来像我们的故障，调用方会去重试。"""
    with _machine(world) as m:
        r = m.post(
            f"/api/v1/distribution/{DOMAIN}/runs",
            json={"runner_ref": f"fleet:{FLEET_REF}/p#1", "role": "concept",
                  "outcome": "ok", "task_id": "abc"},
            headers=_machine_headers(),
        )
    assert r.status_code == 422
    assert "task_id 必须是整数" in r.json()["detail"]


# ------------------------------------------- 机器提交面（舰队自己把产物交上去）


def _proposal_body(source: str, key: str = "machine-corp") -> dict:
    return {
        "source": source, "kind": "company", "external_key": key,
        "body": "机器面提交的主体", "evidence": {"url": "https://e.test/m"},
    }


def test_a_token_cannot_submit_under_another_fleets_source(world):
    """token 只能代表它自己那条登记；换个前缀就是冒用，403 而不是「收下了」。"""
    with _machine(world) as m:
        r = m.post(
            f"/api/v1/distribution/{DOMAIN}/proposals",
            json=_proposal_body("fleet:fleet_other/post_1"),
            headers=_machine_headers(),
        )
    assert r.status_code == 403
    assert "机器面只能以自己的身份提交" in r.json()["detail"]
    assert world.execute(
        "SELECT count(*) AS n FROM domain_proposals"
    ).fetchone()["n"] == 0


def test_a_token_cannot_submit_an_extract_or_agent_source(world):
    """`extract:` 的可信依据是「流水线在网络上到不了」；`agent:`/`user:` 需要人。
    机器面三种都不该接受——否则前缀校验一被绕过，凭据就成了万能身份。"""
    for source in ("extract:qwen:2025-10", "user:someone@example.com", "agent:concept@legal"):
        with _machine(world) as m:
            r = m.post(
                f"/api/v1/distribution/{DOMAIN}/proposals",
                json=_proposal_body(source),
                headers=_machine_headers(),
            )
        assert r.status_code == 403, (source, r.text)
    assert world.execute(
        "SELECT count(*) AS n FROM domain_proposals"
    ).fetchone()["n"] == 0


def test_machine_submission_requires_a_fleet_token(world):
    with _machine(world) as m:
        missing = m.post(
            f"/api/v1/distribution/{DOMAIN}/proposals", json=_proposal_body("fleet:x/p")
        )
    assert missing.status_code == 401
    assert "X-Consumer-Token" in missing.json()["detail"]


def test_a_fleet_reads_only_its_own_proposal_outcomes(world):
    """别人的前缀要 403：空列表读起来是「什么都没发生」，那是一句假话。"""
    with _machine(world) as m:
        own = m.get(
            f"/api/v1/distribution/{DOMAIN}/proposals/outcomes",
            params={"source": f"fleet:{FLEET_REF}/post_1"},
            headers=_machine_headers(),
        )
        stolen = m.get(
            f"/api/v1/distribution/{DOMAIN}/proposals/outcomes",
            params={"source": "fleet:fleet_other/post_1"},
            headers=_machine_headers(),
        )
    assert own.status_code == 200, own.text
    assert stolen.status_code == 403
    assert "只能读取自己来源的结局" in stolen.json()["detail"]


# ------------------------------- 参考客户端 × 真路由（别让接入件只对着假传输绿）


class _FakeResponse:
    """`urlopen` 返回值的最小形状（context manager + read）。"""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> bool:
        return False


def _client_over_app(app, token: str):
    """把 `fleet_client.Client` 的传输层接到 ASGI app 上。

    参考客户端此前只被假传输测过——路径写错、方法写错、把 4xx 当成功，那套测试一条都
    抓不到。这里让它的**真实**路径/请求头/JSON 编解码打到真路由上：接入方要照抄的就是
    这个文件，它自己不能是唯一没碰过真 app 的一段。
    """
    module = _load_fleet_client()
    client = module.Client(base_url="http://bench.test", token=token)
    transport = TestClient(app)   # 真 ASGI 传输层：路由、路径参数、请求头解析、依赖注入全在

    def urlopen(request, timeout=None):  # noqa: ANN001 - 与 urlopen 同签名
        full = request.full_url
        assert full.startswith("http://bench.test"), full
        path = full[len("http://bench.test"):]
        headers = {k.lower(): v for k, v in request.header_items()}
        response = transport.request(
            request.get_method(), path, content=request.data, headers=headers
        )
        if response.status_code >= 400:
            raise urllib.error.HTTPError(
                full, response.status_code, "refused", {}, io.BytesIO(response.content)
            )
        return _FakeResponse(response.content)

    return module, client, urlopen


def test_the_reference_client_speaks_to_the_real_app(world, monkeypatch):
    """六步全用 `fleet_client.Client` 走，一步都不许直连路由。

    断言的是「接入件能干活」：拉单 → 认领 → 回写 → 提交 → 读结局 → 关单。
    """
    import urllib.request

    conn = world
    domain = workspaces.get_domain(conn, domain_key=DOMAIN)
    from src.bench import authoring

    task = authoring.authoring_create_task(
        conn, domain_id=domain["id"], assignee="loop-fleet", title="t-client",
        detail="d", target_kind="estate-gap", target_key="editorial", created_by="lara",
        assignee_kind="fleet", assignee_ref=FLEET_REF,
    )

    app = create_app()
    app.dependency_overrides[get_db] = lambda: conn
    module, client, urlopen = _client_over_app(app, TOKEN)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    orders = client.orders(DOMAIN)
    assert [o["id"] for o in orders["work_orders"]] == [task["id"]]

    claimed = client.claim(DOMAIN, task["id"])
    assert claimed["task"]["status"] == "in_progress"
    assert client.claim(DOMAIN, task["id"])["created"] is False   # 自己的重试幂等

    runner_ref = f"fleet:{FLEET_REF}/post_client#1"
    assert client.record_run(
        DOMAIN, runner_ref=runner_ref, role="concept", outcome="ok",
        counts={"drafts": 1}, task_id=task["id"],
    )["created"] is True
    assert client.read_runs(DOMAIN, runner_ref=runner_ref)["count"] == 1

    filed = client.submit(
        DOMAIN, source=f"fleet:{FLEET_REF}/post_client", kind="company",
        external_key="client-corp", body="接入件交的主体",
        evidence={"url": "https://e.test/client"},
    )
    assert filed["created"] is True

    # 域负责人确认（会话身份）→ 舰队读自己的结局。
    with _human(conn) as h:
        confirmed = h.post(f"/d/{DOMAIN}/inbox/{filed['id']}/confirm", follow_redirects=False)
    assert confirmed.status_code == 303
    assert "err=1" not in confirmed.headers["location"]

    outcomes = client.outcomes(DOMAIN, source=f"fleet:{FLEET_REF}/post_client")
    assert outcomes["outcomes"][0]["state"] == "confirmed"

    assert client.complete(DOMAIN, task["id"], note="接入件关单", artifact_refs=None)[
        "task"
    ]["status"] == "done"


def test_the_reference_client_turns_a_403_into_a_refusal(world, monkeypatch):
    """真路由回来的 403 必须被识别成 `Refused`（退出码 1），不是崩或当成功。"""
    import urllib.request

    conn = world
    app = create_app()
    app.dependency_overrides[get_db] = lambda: conn
    module, client, urlopen = _client_over_app(app, TOKEN)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    with pytest.raises(module.Refused) as exc:
        client.outcomes(DOMAIN, source="fleet:fleet_other/post_1")
    assert "403" in str(exc.value) and "只能读取自己来源的结局" in str(exc.value)


# ------------------------------------------------------------------ 机器读面


def test_a_fleet_sees_only_its_own_open_orders(world):
    """舰队看不见的活没法领。读面只给「派给本舰队、本域、未关闭」的那几张。"""
    conn = world
    domain = workspaces.get_domain(conn, domain_key=DOMAIN)
    from src.bench import authoring

    def task(key, *, assignee_kind="fleet", ref=FLEET_REF, status="pending"):
        t = authoring.authoring_create_task(
            conn, domain_id=domain["id"], assignee=f"x-{key}", title=f"t-{key}",
            detail="d", target_kind="estate-gap", target_key=key, created_by="lara",
            assignee_kind=assignee_kind, assignee_ref=ref,
        )
        if status == "in_progress":
            authoring.authoring_claim_task(conn, task_id=t["id"], actor=ref)
        elif status == "done":
            authoring.authoring_claim_task(conn, task_id=t["id"], actor=ref)
            authoring.authoring_complete_task(conn, task_id=t["id"], actor=ref)
        return t

    task("ontology")
    task("knowledge", status="in_progress")
    task("eval", status="done")             # 已关闭：不是待领的活
    task("quality:grounding", assignee_kind="human", ref=None)  # 不是舰队单
    distribution.register_consumer(
        conn, name="other-fleet", domains=[DOMAIN],
        token_hash=hashlib.sha256(b"other2").hexdigest(), created_by="seed",
        kind="fleet", fleet_ref="fleet_other",
    )
    task("quality:evidence", ref="fleet_other")  # 别人家的单

    events_before = conn.execute(
        "SELECT count(*) AS n FROM authoring_events"
    ).fetchone()["n"]
    with _machine(conn) as m:
        first = m.get(f"/api/v1/distribution/{DOMAIN}/work-orders",
                      headers=_machine_headers())
        second = m.get(f"/api/v1/distribution/{DOMAIN}/work-orders",
                       headers=_machine_headers())

    assert first.status_code == 200, first.text
    body = first.json()
    assert body["fleet_ref"] == FLEET_REF
    assert body["count"] == 2
    keys = {w["target_key"] for w in body["work_orders"]}
    assert keys == {"ontology", "knowledge"}
    claimed = {w["target_key"]: w["claimed_by"] for w in body["work_orders"]}
    assert claimed == {"ontology": None, "knowledge": FLEET_REF}
    # 载荷字段：工单标识/目标/标题/详情/创建时间/状态都在。
    sample = body["work_orders"][0]
    for field in ("id", "target_kind", "target_key", "title", "detail",
                  "created_at", "status"):
        assert field in sample, field

    # 重复拉取无副作用：载荷逐字相同、事件流一行不增、状态不变。
    assert second.json() == body
    assert conn.execute(
        "SELECT count(*) AS n FROM authoring_events"
    ).fetchone()["n"] == events_before
    statuses = {
        r["target_key"]: r["status"]
        for r in conn.execute("SELECT target_key, status FROM authoring_tasks").fetchall()
    }
    assert statuses["ontology"] == "pending" and statuses["knowledge"] == "in_progress"


def test_the_order_pull_requires_a_fleet_token(world):
    with _machine(world) as m:
        missing = m.get(f"/api/v1/distribution/{DOMAIN}/work-orders")
    assert missing.status_code == 401
    with _machine(world) as m:
        other_domain = m.get("/api/v1/distribution/not-bound/work-orders",
                            headers=_machine_headers())
    assert other_domain.status_code == 403


def test_another_fleets_claim_is_still_a_conflict(world):
    """幂等只放自己的重试；别的舰队来领同一张单仍然必须被如实拒绝。"""
    conn = world
    domain = workspaces.get_domain(conn, domain_key=DOMAIN)
    from src.bench import authoring

    distribution.register_consumer(
        conn, name="second-fleet", domains=[DOMAIN],
        token_hash=hashlib.sha256(b"second").hexdigest(), created_by="seed",
        kind="fleet", fleet_ref="fleet_second",
    )
    # 一张派给 fleet_second 的单：本舰队（loop-fleet）连碰都不该碰到它。
    task = authoring.authoring_create_task(
        conn, domain_id=domain["id"], assignee="second-fleet", title="t", detail="d",
        target_kind="estate-gap", target_key="ontology", created_by="lara",
        assignee_kind="fleet", assignee_ref="fleet_second",
    )
    with _machine(conn) as m:
        r = m.post(f"/api/v1/distribution/{DOMAIN}/work-orders/{task['id']}/claim",
                   headers=_machine_headers())
    assert r.status_code == 403


def test_completing_twice_is_an_idempotent_hit(world):
    conn = world
    domain = workspaces.get_domain(conn, domain_key=DOMAIN)
    from src.bench import authoring

    task = authoring.authoring_create_task(
        conn, domain_id=domain["id"], assignee="loop-fleet", title="t", detail="d",
        target_kind="estate-gap", target_key="ontology", created_by="lara",
        assignee_kind="fleet", assignee_ref=FLEET_REF,
    )
    with _machine(conn) as m:
        m.post(f"/api/v1/distribution/{DOMAIN}/work-orders/{task['id']}/claim",
               headers=_machine_headers())
        first = m.post(f"/api/v1/distribution/{DOMAIN}/work-orders/{task['id']}/complete",
                       headers=_machine_headers())
        second = m.post(f"/api/v1/distribution/{DOMAIN}/work-orders/{task['id']}/complete",
                        headers=_machine_headers())
    assert first.status_code == 200 and first.json()["created"] is True
    assert second.status_code == 200, second.text
    assert second.json()["created"] is False
    dones = [e for e in second.json()["task"]["transitions"] if e.get("to") == "done"]
    assert len(dones) == 1, "重试不得再落一条完成事件"


# ------------------------------------- 提交前预检（409：目标状态与这次提交冲突）


def _seed_live_unit(db, key: str = "machine-corp") -> dict:
    from src.bench import authoring

    return authoring.authoring_create_unit(
        db, domain_key=DOMAIN, kind="company", external_key=key,
        body="既有正文（不得被提案改写）", operator="seed",
    )


def test_a_duplicate_key_is_409_at_the_machine_face_not_a_pending_row(world):
    """键已在本体时机器面回 409 + 机器可读理由，且不落提案行。

    为什么要在提交口拒：确认一步走的是单位 upsert ⇒ 批准一条重复键提案
    等于**静默改写**既有单位正文，而人看到的是「新增」。
    """
    _seed_live_unit(world, "machine-corp")
    with _machine(world) as m:
        r = m.post(
            f"/api/v1/distribution/{DOMAIN}/proposals",
            json=_proposal_body(f"fleet:{FLEET_REF}/post_1", key="machine-corp"),
            headers=_machine_headers(),
        )
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["reason"] == "key_already_live"
    assert "machine-corp" in detail["message"]
    assert detail["hint"]
    assert world.execute(
        "SELECT count(*) AS n FROM domain_proposals"
    ).fetchone()["n"] == 0
    from src.bench import authoring

    kept = authoring.authoring_get_unit(
        world, domain_key=DOMAIN, kind="company", external_key="machine-corp"
    )
    assert kept["body"] == "既有正文（不得被提案改写）"


def test_a_relationship_with_a_missing_endpoint_is_409(world):
    """端点未入库 ⇒ 409 endpoints_missing，点名缺的那个；确认时必失败的事
    不该先占住负责人的确认位。"""
    _seed_live_unit(world, "co-left")
    with _machine(world) as m:
        r = m.post(
            f"/api/v1/distribution/{DOMAIN}/proposals",
            json={
                "source": f"fleet:{FLEET_REF}/post_1",
                "kind": "belongs_to",
                "external_key": "co-left->belongs_to:co-ghost",
                "body": "左属于右",
                "evidence": {"from_key": "co-left", "to_key": "co-ghost"},
            },
            headers=_machine_headers(),
        )
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["reason"] == "endpoints_missing"
    assert "co-ghost" in detail["message"]
    assert world.execute(
        "SELECT count(*) AS n FROM domain_proposals"
    ).fetchone()["n"] == 0


def test_an_out_of_vocabulary_kind_is_409_at_the_machine_face(world):
    """词表外的 kind ⇒ 409 kind_not_in_vocabulary，不落提案行。

    这一类的人群是直连提交方：抽取流水线提交前已按同一张模板词表预筛，
    所以只有 MCP/控制台能把 `n:1` 这种词表外写法送进箱（生产实证：legal 域
    3 条 `n:1` 的 source 全是 `fleet:`）。确认时 `_lane_for_kind` 照样抛，
    所以它在箱里唯一的作用就是占住负责人的确认位。
    """
    with _machine(world) as m:
        r = m.post(
            f"/api/v1/distribution/{DOMAIN}/proposals",
            json={
                "source": f"fleet:{FLEET_REF}/post_1",
                "kind": "n:1",
                "external_key": "co-a->n:1:co-b",
                "body": "探针草稿里的基数写法",
                "evidence": {"from_key": "co-a", "to_key": "co-b"},
            },
            headers=_machine_headers(),
        )
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["reason"] == "kind_not_in_vocabulary"
    assert "n:1" in detail["message"]
    assert detail["hint"]
    assert world.execute(
        "SELECT count(*) AS n FROM domain_proposals"
    ).fetchone()["n"] == 0
