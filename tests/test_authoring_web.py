"""Web tests for the expert authoring surface (change
``add-expert-authoring-surface``).

Covers the web halves of OpenSpec tasks 3.1 (词表执法), 3.2 (域隔离写作),
3.3 (变更事件流), 3.4 (任务指派与工作台) and all of 3.5 (工作台 RBAC 三档),
asserting the SCENARIO semantics of
``openspec/changes/add-expert-authoring-surface/specs/expert-authoring/spec.md``
and the ``domain-workspace`` delta — through the HTTP surface only
(``src/web/routes/authoring.py``), never by reaching past the gates.

World: one template (entity_types=[company, indicator], relationship_kinds=
[belongs_to]), domain A ``aw-key`` with alice=expert / rae=annotator /
lara=lead, domain B ``bw-key`` with bob=expert (separate membership).

Client pattern: ``_client(db, user)`` à la ``test_admin_web.py`` —
``create_app()`` with ``dependency_overrides`` for ``get_db`` +
``get_current_user``; the override also sets ``request.state.user`` so the
base-chrome nav (``my_domains`` / ``has_scope``) renders from the same
identity the route gates saw. No workbench route is auth-exempt, so the real
signed-cookie pattern is not needed here.

Locale: the suite runs with the default ``zh`` catalog. Visible-text
assertions use zh strings of ``src/web/i18n.py`` — but every catalog string
also rides the ``window.__LOCALE__`` bootstrap on every page, so positive
assertions anchor on rendered MARKUP (``<span class="badge">…</span>``,
``<h2>…</h2>``, ``href="…"``) and negative assertions use custom strings
(domain names, unit keys, bodies) that exist only in seeded data.

Seeding goes through the C1/C2 kernel APIs (``src.bench.templates`` /
``src.bench.workspaces``) and, for kernel-state assertions, the authoring API
(``src.bench.authoring``) — no raw SQL where an API exists. One exception:
``knowledge_units`` is NOT in ``conftest._ALL_TABLES`` (no truncate between
tests) and the kernel has no physical-delete API, so ``_seed_world`` deletes
the module's namespaces directly to keep tests order-independent.

Vocabulary note (task 3.1 web half): the routes 404 out-of-vocabulary kinds
BEFORE the kernel runs (``_kind_lane`` gate — the same 出表 kind 浏览 404 the
tasks mandate for browse), so the kernel's vocabulary ``ValueError`` (which
names the full allowed list and would surface as the ``flash.unit_failed``
error detail) is not reachable over HTTP. The observable HTTP contract
asserted here: rejected with 404 naming the kind/template, zero KU rows and
zero events.
"""

from __future__ import annotations

from html import unescape
from urllib.parse import parse_qs, quote, urlparse

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.bench import authoring as bench_authoring
from src.bench import templates as bench_templates
from src.bench import workspaces
from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user
from src.web.deps import get_db

# A structurally complete template schema (all four vocabularies + the corpus
# declaration); tier/sensitivity sets must equal the kernel's canonical tuples.
# The authoring vocabularies under test: two entity kinds, one relationship kind.
VALID_SCHEMA = {
    "entity_types": ["company", "indicator"],
    "concept_structures": {"indicator": ["name", "unit"]},
    "relationship_kinds": ["belongs_to"],
    "tier_vocabulary": ["gold", "silver", "bronze", "raw"],
    "sensitivity_vocabulary": ["public", "internal", "confidential"],
    "corpus_declaration": {"source_types": []},
}

DOMAIN_A_NAME = "甲域"  # alice / rae / lara belong here
DOMAIN_B_NAME = "乙域"  # bob's domain — must never leak A's content

A_KEY = "aw-key"
B_KEY = "bw-key"

_READ_WRITE = ["content:read", "content:write"]


# --- seed + client helpers -------------------------------------------------- #


def _seed_world(conn) -> dict:
    """One template, two domains, A: alice=expert rae=annotator lara=lead; B: bob.

    The two domains anchor the SAME template so vocabulary differences never
    masquerade as isolation differences. ``knowledge_units`` is not truncated
    by the shared conftest fixture, so this module's namespaces are cleared
    explicitly — every test starts from an empty ontology regardless of order.
    """
    conn.execute(
        "DELETE FROM knowledge_units WHERE namespace IN (%s, %s)", (A_KEY, B_KEY)
    )
    conn.commit()
    bench_templates.create_template(
        conn, name="authoring-template", schema=dict(VALID_SCHEMA), created_by="seed"
    )
    a = workspaces.instantiate_domain(
        conn, key=A_KEY, name=DOMAIN_A_NAME,
        template_name="authoring-template", template_version=None, created_by="seed",
    )
    b = workspaces.instantiate_domain(
        conn, key=B_KEY, name=DOMAIN_B_NAME,
        template_name="authoring-template", template_version=None, created_by="seed",
    )
    workspaces.add_member(conn, domain_id=a["id"], user_id="alice", role="expert", added_by="seed")
    workspaces.add_member(conn, domain_id=a["id"], user_id="rae", role="annotator", added_by="seed")
    workspaces.add_member(conn, domain_id=a["id"], user_id="lara", role="lead", added_by="seed")
    workspaces.add_member(conn, domain_id=b["id"], user_id="bob", role="expert", added_by="seed")
    return {"a": a, "b": b}


def _user(sub: str, scopes: list[str]) -> User:
    """Override-pattern identity; ``_operator_of`` stamps ``user.email``."""
    return User(
        sub=sub, name=sub, email=f"{sub}@example.com",
        scopes=list(scopes), channel="test",
    )


def _client(db, user: User) -> TestClient:
    """App with ``get_db`` + ``get_current_user`` overridden to ``user``.

    Mirrors the real dependency's chrome contract by setting
    ``request.state.user`` (the template context processor and ``has_scope`` /
    ``my_domains`` read it), so nav assertions run against the same identity
    the route dependencies enforced.
    """
    app = create_app()

    def _current_user(request: Request) -> User:
        request.state.user = user
        return user

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _current_user
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_idp(monkeypatch):
    """Neutralize the fail-closed startup IdP probe for every app built here."""
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)


def _params(location: str) -> dict:
    """Flash query params of a redirect Location, decoded."""
    return {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}


def _create_unit(client: TestClient, kind: str = "company", key: str = "ai-corp",
                 body: str = "人工智能公司条目", tags: str = "status=draft") -> str:
    """POST one entity through the workbench form as the client's user; 303."""
    r = client.post(
        f"/d/{A_KEY}/units/{quote(kind, safe='')}/new",
        data={"external_key": key, "body": body, "tags": tags},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    assert _params(r.headers["location"])["msg"] == "flash.unit_created"
    return r.headers["location"]


def _assign_task(client: TestClient, assignee: str, title: str) -> str:
    """POST one task assignment through the lead form as the client's user."""
    r = client.post(
        f"/d/{A_KEY}/tasks/new",
        data={"assignee": assignee, "title": title, "detail": "",
              "target_kind": "company", "target_key": ""},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    assert _params(r.headers["location"])["msg"] == "flash.task_assigned"
    return r.headers["location"]


def _pending_task(conn, assignee: str) -> dict:
    """The single pending task assigned to ``assignee`` in domain A."""
    a = workspaces.get_domain(conn, domain_key=A_KEY)
    tasks = bench_authoring.authoring_list_tasks(
        conn, domain_id=a["id"], assignee=assignee, status="pending"
    )
    assert len(tasks) == 1
    return tasks[0]


# =========================================================================== #
# Task 3.5 — 工作台 RBAC 三档 (read annotator+ / write expert+ / assign lead+)  #
# =========================================================================== #


def test_annotator_reads_workbench_but_cannot_write(seeded_db):
    """标注员只读 (domain-workspace scenario): rae sees the overview but her
    create POST is refused with the DOMAIN-permission denial — she holds
    content:write, so the 403 无该域权限 proves the role gate (annotator <
    expert), not a scope error. Zero units, zero events."""
    world = _seed_world(seeded_db)
    rae = _user("rae", _READ_WRITE)
    with _client(seeded_db, rae) as c:
        home = c.get(f"/d/{A_KEY}")
        assert home.status_code == 200
        assert DOMAIN_A_NAME in home.text
        assert '<span class="badge">标注员</span>' in home.text     # active role
        assert '<h2>我的任务</h2>' in home.text                      # workbench chrome
        # The vocabulary display doubles as the kind list — all three kinds.
        assert "company" in home.text and "indicator" in home.text
        assert "belongs_to" in home.text
        # Read reaches the browse lane too.
        assert c.get(f"/d/{A_KEY}/browse/company").status_code == 200

        denied = c.post(
            f"/d/{A_KEY}/units/company/new",
            data={"external_key": "sneaky", "body": "标注员越权写入"},
            follow_redirects=False,
        )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "无该域权限"  # role denial, NOT missing scope
    assert bench_authoring.authoring_list_units(seeded_db, domain_key=A_KEY) == []
    assert bench_authoring.authoring_events_for(
        seeded_db, domain_id=world["a"]["id"]
    ) == []


def test_expert_creates_unit_via_form_and_lands_raw_provenance(seeded_db):
    """词表内创作成功 (expert-authoring scenario): alice's form POST redirects
    to the new unit's detail page; the KU lands in the domain's namespace at
    tier raw with the operator in the provenance — the kernel KU 收口, and
    the unit shows up in browse."""
    _seed_world(seeded_db)
    alice = _user("alice", _READ_WRITE)
    with _client(seeded_db, alice) as c:
        location = _create_unit(c, key="ai-corp", body="人工智能公司条目",
                                tags="status=draft")
        assert location.startswith(f"/d/{A_KEY}/units/company/ai-corp")

        detail = c.get(location)
        assert detail.status_code == 200
        assert "ai-corp" in detail.text

        browse = c.get(f"/d/{A_KEY}/browse/company")
        assert browse.status_code == 200
        assert "ai-corp" in browse.text and "人工智能公司条目" in browse.text

    unit = bench_authoring.authoring_get_unit(
        seeded_db, domain_key=A_KEY, kind="company", external_key="ai-corp"
    )
    assert unit is not None
    assert unit["namespace"] == A_KEY          # KU 以域 key 为 namespace 落库
    assert unit["tier"] == "raw"               # tier 初始为 raw
    assert unit["provenance"]["operator"] == "alice@example.com"  # 操作者入溯源
    assert unit["provenance"]["via"] == "authoring"
    assert unit["tags"] == {"status": "draft"}
    assert unit["body"] == "人工智能公司条目"


def test_lead_and_admin_also_write_admin_reads_without_membership(seeded_db):
    """写档上界: lead writes like an expert; the platform admin ('*' scope,
    zero membership) both reads the workbench (管理员 badge via the bypass)
    and creates — require_domain_role's admin bypass is not write-only."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as c:
        location = _create_unit(c, kind="indicator", key="ind-registered-cap",
                                body="注册资本指标")
        assert "/d/" + A_KEY in location
    with _client(seeded_db, _user("admin-u", ["*"])) as c:
        home = c.get(f"/d/{A_KEY}")
        assert home.status_code == 200
        assert '<span class="badge">管理员</span>' in home.text  # bypass role badge
        assert DOMAIN_A_NAME in home.text
        location = _create_unit(c, key="adm-unit", body="管理员直通创建")
        assert location.startswith(f"/d/{A_KEY}/units/company/adm-unit")

    keys = {u["external_key"] for u in bench_authoring.authoring_list_units(
        seeded_db, domain_key=A_KEY)}
    assert keys == {"ind-registered-cap", "adm-unit"}


def test_non_member_fail_closed_403_not_404_on_every_workbench_route(seeded_db):
    """非成员不可见工作台 (expert-authoring scenario): an authenticated user
    with content:read+content:write but NO membership gets 403 无该域权限 —
    fail-closed, never a disguised 404 — on the read route AND on every write
    route, with zero data written."""
    world = _seed_world(seeded_db)
    outsider = _user("outsider", _READ_WRITE)
    with _client(seeded_db, outsider) as c:
        r = c.get(f"/d/{A_KEY}")
        assert r.status_code == 403  # the permission denial, NOT a 404
        assert r.json()["detail"] == "无该域权限"
        assert DOMAIN_A_NAME not in r.text  # zero exposure of the domain

        assert c.post(
            f"/d/{A_KEY}/units/company/new",
            data={"external_key": "intruder", "body": "x"},
            follow_redirects=False,
        ).status_code == 403
        assert c.post(
            f"/d/{A_KEY}/tasks/1/status", data={"to_status": "done"},
            follow_redirects=False,
        ).status_code == 403

    assert bench_authoring.authoring_list_units(seeded_db, domain_key=A_KEY) == []
    assert bench_authoring.authoring_events_for(
        seeded_db, domain_id=world["a"]["id"]
    ) == []


def test_scope_gate_runs_first_for_member_without_content_read(seeded_db):
    """两道序贯 (scope ▶ domain role): a MEMBER whose scopes lack content:read
    gets the scope denial, not the domain denial; a user failing BOTH gates
    also sees the scope message — require_scope composes before
    require_domain_role on every workbench route."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("alice", ["content:write"])) as c:
        r = c.get(f"/d/{A_KEY}")  # member: the domain gate would pass
    assert r.status_code == 403
    assert r.json()["detail"] == "missing scope: content:read"

    with _client(seeded_db, _user("nobody", [])) as c:
        r = c.get(f"/d/{A_KEY}")  # fails both gates...
    assert r.status_code == 403
    assert r.json()["detail"] == "missing scope: content:read"  # ...scope speaks first


# =========================================================================== #
# Task 3.2 — 域隔离写作 via HTTP                                               #
# =========================================================================== #


def test_cross_domain_isolation_a_unit_never_reaches_b(seeded_db):
    """隔离写作 (expert-authoring scenario): alice's unit exists only under
    A's namespace. Alice (no B membership) is 403'd fail-closed on B's
    workbench read AND write; B's member sweeps every reachable 200 response
    and finds no trace of A's unit; B's namespace stays empty."""
    _seed_world(seeded_db)
    alice = _user("alice", _READ_WRITE)
    with _client(seeded_db, alice) as c:
        _create_unit(c, key="iso-unit", body="甲域独有内容标记", tags="")

        # Cross-domain read: fail-closed 403, not a 404.
        r = c.get(f"/d/{B_KEY}")
        assert r.status_code == 403
        assert r.json()["detail"] == "无该域权限"
        # Cross-domain write: the same gate, nothing written.
        w = c.post(
            f"/d/{B_KEY}/units/company/new",
            data={"external_key": "intruder", "body": "x"},
            follow_redirects=False,
        )
        assert w.status_code == 403
        assert w.json()["detail"] == "无该域权限"

        # Positive control: alice's own domain browse carries the unit.
        own = c.get(f"/d/{A_KEY}/browse/company")
        assert own.status_code == 200
        assert "iso-unit" in own.text and "甲域独有内容标记" in own.text

    # B's namespace is untouched by the cross-domain attempts.
    assert bench_authoring.authoring_list_units(seeded_db, domain_key=B_KEY) == []

    # B member sweep: no 200 response reachable by bob mentions A's unit.
    bob = _user("bob", _READ_WRITE)
    with _client(seeded_db, bob) as c:
        sweep = [
            c.get(f"/d/{B_KEY}"),
            c.get(f"/d/{B_KEY}/browse/company"),
            c.get(f"/d/{B_KEY}/browse/indicator"),
            c.get(f"/d/{B_KEY}/browse/belongs_to"),
        ]
    for response in sweep:
        assert response.status_code == 200
        assert "iso-unit" not in response.text
        assert "甲域独有内容标记" not in response.text
        assert "aw-key" not in response.text


# =========================================================================== #
# Task 3.1 web half — 词表执法 via HTTP                                        #
# =========================================================================== #


def test_out_of_vocab_kind_create_rejected_zero_rows(seeded_db):
    """出表 kind 拒绝 (expert-authoring scenario): creating with a kind outside
    entity_types — and a relationship kind outside relationship_kinds — is
    refused, no KU and no event. (The routes reject with 404 naming the
    kind/template BEFORE the kernel's vocabulary gate — see module docstring.)
    """
    world = _seed_world(seeded_db)
    alice = _user("alice", _READ_WRITE)
    with _client(seeded_db, alice) as c:
        entity = c.post(
            f"/d/{A_KEY}/units/mineral/new",
            data={"external_key": "m1", "body": "出表实体"},
            follow_redirects=False,
        )
        relationship = c.post(
            f"/d/{A_KEY}/units/acquires/new",
            data={"from_key": "c1", "to_key": "c2", "body": "出表关系"},
            follow_redirects=False,
        )
    assert entity.status_code == 404
    assert "mineral" in entity.json()["detail"]
    assert relationship.status_code == 404
    assert "acquires" in relationship.json()["detail"]

    assert bench_authoring.authoring_list_units(seeded_db, domain_key=A_KEY) == []
    assert bench_authoring.authoring_events_for(
        seeded_db, domain_id=world["a"]["id"]
    ) == []


def test_out_of_vocab_kind_browse_is_404(seeded_db):
    """出表 kind 浏览 404 (tasks 2.2): browse and the create form both 404 for
    kinds outside the anchored template's vocabularies, in either lane."""
    _seed_world(seeded_db)
    alice = _user("alice", _READ_WRITE)
    with _client(seeded_db, alice) as c:
        assert c.get(f"/d/{A_KEY}/browse/mineral").status_code == 404
        assert c.get(f"/d/{A_KEY}/browse/acquires").status_code == 404
        assert c.get(f"/d/{A_KEY}/units/mineral/new").status_code == 404


def test_relationship_create_derives_key_round_trip(seeded_db):
    """关系创作: the form carries from_key/to_key; the kernel derives
    ``{from_key}->{kind}:{to_key}`` and the redirect lands on the derived
    key's detail page with the URL-encoded key round-tripping intact."""
    _seed_world(seeded_db)
    alice = _user("alice", _READ_WRITE)
    with _client(seeded_db, alice) as c:
        r = c.post(
            f"/d/{A_KEY}/units/belongs_to/new",
            data={"from_key": "c1", "to_key": "c2", "body": "隶属关系"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        location = r.headers["location"]
        # The derived key, percent-encoded in the URL (-> and : are unsafe).
        assert location.startswith(
            f"/d/{A_KEY}/units/belongs_to/c1-%3Ebelongs_to%3Ac2"
        )
        assert _params(location)["msg"] == "flash.unit_created"

        # The encoded key round-trips: the detail page renders it decoded
        # (Jinja autoescape shows '>' as &gt; in the HTML source).
        detail = c.get(location)
        assert detail.status_code == 200
        assert "c1->belongs_to:c2" in unescape(detail.text)
        assert "<code>c1</code>" in detail.text and "<code>c2</code>" in detail.text

    unit = bench_authoring.authoring_get_unit(
        seeded_db, domain_key=A_KEY, kind="belongs_to",
        external_key="c1->belongs_to:c2",
    )
    assert unit is not None
    assert unit["attrs"]["from"] == "c1" and unit["attrs"]["to"] == "c2"
    assert unit["kind"] == "belongs_to"


# =========================================================================== #
# Task 3.3 web half — 变更事件流 via web                                       #
# =========================================================================== #


def test_event_trail_create_update_delete_visible_on_detail(seeded_db):
    """变更留痕: after create → edit → soft delete the unit's detail page shows
    all three ops stamped with the operator and the update's before→after
    bodies; the deleted unit leaves browse but stays viewable detail-direct
    with the deleted notice and its intact event history."""
    _seed_world(seeded_db)
    alice = _user("alice", _READ_WRITE)
    with _client(seeded_db, alice) as c:
        created = _create_unit(c, key="doc-1", body="草案正文第一版",
                               tags="status=draft")

        edited = c.post(
            f"{created.split('?')[0]}/edit",
            data={"body": "草案正文第二版", "tags": "status=draft"},
            follow_redirects=False,
        )
        assert edited.status_code == 303
        assert _params(edited.headers["location"])["msg"] == "flash.unit_updated"

        deleted = c.post(
            f"{created.split('?')[0]}/delete", data={}, follow_redirects=False
        )
        assert deleted.status_code == 303
        assert deleted.headers["location"].startswith(
            f"/d/{A_KEY}/browse/company"
        )
        assert _params(deleted.headers["location"])["msg"] == "flash.unit_deleted"

        # Soft delete: excluded from browse...
        browse = c.get(f"/d/{A_KEY}/browse/company")
        assert browse.status_code == 200
        assert "doc-1" not in browse.text

        # ...but detail-direct still renders, with the deleted notice.
        detail = c.get(f"/d/{A_KEY}/units/company/doc-1")
        assert detail.status_code == 200
        assert 'role="alert">该条目已软删除' in detail.text
        assert '<h2>变更历史</h2>' in detail.text

    # The three ops, each stamped with the operator.
    ops = ('<span class="badge">创建</span>', '<span class="badge">更新</span>',
           '<span class="badge">删除</span>')
    for op_badge in ops:
        assert op_badge in detail.text
    assert detail.text.count("alice@example.com") >= 3  # one per event row
    # The update event carries the before→after summary of the body.
    assert "草案正文第一版 → 草案正文第二版" in detail.text

    # Kernel truth behind the page: exactly three append-only events.
    a = workspaces.get_domain(seeded_db, domain_key=A_KEY)
    events = bench_authoring.authoring_events_for(seeded_db, domain_id=a["id"])
    assert [ev["op"] for ev in events] == ["delete", "update", "create"]  # newest first
    assert events[1]["before"]["body"] == "草案正文第一版"
    assert events[1]["after"]["body"] == "草案正文第二版"
    # The delete event carries the full prior state and a null after; the
    # soft-delete marker lives on the KU row itself, not in the event.
    assert events[0]["before"]["body"] == "草案正文第二版"
    assert events[0]["before"]["tags"] == {"status": "draft"}
    assert events[0]["after"] is None
    unit = bench_authoring.authoring_get_unit(
        seeded_db, domain_key=A_KEY, kind="company", external_key="doc-1"
    )
    assert unit["tags"]["deleted"] is True  # row flagged, body preserved
    assert unit["body"] == "草案正文第二版"


# =========================================================================== #
# Task 3.4 web half — 任务指派、领取、完成、取消 via HTTP                        #
# =========================================================================== #


def test_task_lifecycle_assign_claim_complete_with_trail(seeded_db):
    """指派到完成 (expert-authoring scenario): the lead assigns to a domain
    member, the assignee claims then completes, every hop redirects with its
    flash, the kernel trail records who moved what, and the reader's workbench
    reflects each status."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as lead:
        location = _assign_task(lead, "alice", "撰写公司条目")
        assert _params(location)["name"] == "alice"

    task = _pending_task(seeded_db, "alice")
    assert task["title"] == "撰写公司条目"
    assert task["target_kind"] == "company"
    assert task["created_by"] == "lara@example.com"
    assert task["transitions"] == [
        {"from": None, "to": "pending", "by": "lara@example.com",
         "at": task["transitions"][0]["at"]},
    ]

    alice = _user("alice", _READ_WRITE)
    with _client(seeded_db, alice) as c:
        # The reader sees the pending assignment with a claim affordance.
        home = c.get(f"/d/{A_KEY}")
        assert "撰写公司条目" in home.text
        assert '<span class="badge">待领取</span>' in home.text
        assert ">领取</button>" in home.text

        claim = c.post(
            f"/d/{A_KEY}/tasks/{task['id']}/status",
            data={"to_status": "in_progress"}, follow_redirects=False,
        )
        assert claim.status_code == 303
        assert _params(claim.headers["location"])["msg"] == "flash.task_status_updated"

        done = c.post(
            f"/d/{A_KEY}/tasks/{task['id']}/status",
            data={"to_status": "done"}, follow_redirects=False,
        )
        assert done.status_code == 303

        # The trail is visible to the reader: the task now shows done.
        after = c.get(f"/d/{A_KEY}")
        assert '<span class="badge">已完成</span>' in after.text

    final = bench_authoring.authoring_get_task(seeded_db, task_id=task["id"])
    assert final["status"] == "done"
    assert [entry["to"] for entry in final["transitions"]] == [
        "pending", "in_progress", "done",
    ]
    assert [entry["by"] for entry in final["transitions"]] == [
        "lara@example.com", "alice", "alice",
    ]


def test_annotator_cannot_claim_expert_cannot_assign_or_cancel(seeded_db):
    """角色边界: the annotator's claim is refused at the route (role gate, she
    holds content:write); the expert can neither open nor post the lead-only
    assignment form; the expert's cancel attempt is refused in-handler by the
    lead rule (flash, not exception), leaving the task untouched."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as lead:
        _assign_task(lead, "alice", "待领取任务")
    task = _pending_task(seeded_db, "alice")

    rae = _user("rae", _READ_WRITE)
    with _client(seeded_db, rae) as c:
        r = c.post(
            f"/d/{A_KEY}/tasks/{task['id']}/status",
            data={"to_status": "in_progress"}, follow_redirects=False,
        )
    assert r.status_code == 403
    assert r.json()["detail"] == "无该域权限"  # annotator < expert at the role gate

    alice = _user("alice", _READ_WRITE)
    with _client(seeded_db, alice) as c:
        assert c.get(f"/d/{A_KEY}/tasks/new").status_code == 403
        post = c.post(
            f"/d/{A_KEY}/tasks/new",
            data={"assignee": "alice", "title": "越权指派"},
            follow_redirects=False,
        )
        assert post.status_code == 403
        assert post.json()["detail"] == "无该域权限"

        cancel = c.post(
            f"/d/{A_KEY}/tasks/{task['id']}/status",
            data={"to_status": "cancelled"}, follow_redirects=False,
        )
    assert cancel.status_code == 303  # in-handler refusal -> error flash
    params = _params(cancel.headers["location"])
    assert params["msg"] == "flash.task_failed" and params["err"] == "1"
    assert "lead" in params["detail"]

    still = bench_authoring.authoring_get_task(seeded_db, task_id=task["id"])
    assert still["status"] == "pending" and len(still["transitions"]) == 1


def test_lead_cancels_task_with_trail(seeded_db):
    """取消留痕: the lead cancels an active task; the trail records the lead's
    hop to cancelled."""
    _seed_world(seeded_db)
    lara = _user("lara", _READ_WRITE)
    with _client(seeded_db, lara) as c:
        _assign_task(c, "rae", "核验指标条目")
        task = _pending_task(seeded_db, "rae")
        r = c.post(
            f"/d/{A_KEY}/tasks/{task['id']}/status",
            data={"to_status": "cancelled"}, follow_redirects=False,
        )
    assert r.status_code == 303
    assert _params(r.headers["location"])["msg"] == "flash.task_status_updated"

    final = bench_authoring.authoring_get_task(seeded_db, task_id=task["id"])
    assert final["status"] == "cancelled"
    assert final["transitions"][-1] == {
        "from": "pending", "to": "cancelled", "by": "lara",  # actor = user.sub
        "at": final["transitions"][-1]["at"],
    }


def test_foreign_domain_task_id_is_404_no_leak(seeded_db):
    """跨域任务零泄漏: even a member of BOTH domains gets an honest 404 —
    never the task — for another domain's task id, and B's namespace renders
    none of A's content (every kernel call is pinned to the path's domain)."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as lead:
        _assign_task(lead, "alice", "甲域任务")
    alice = _user("alice", _READ_WRITE)
    with _client(seeded_db, alice) as c:
        _create_unit(c, key="iso-unit", body="甲域独有内容标记", tags="")

    # Second membership: alice joins B as an expert via the kernel API.
    b = workspaces.get_domain(seeded_db, domain_key=B_KEY)
    workspaces.add_member(seeded_db, domain_id=b["id"], user_id="alice",
                          role="expert", added_by="seed")
    task_a = _pending_task(seeded_db, "alice")

    with _client(seeded_db, alice) as c:
        # B is now readable — but carries nothing of A's.
        assert c.get(f"/d/{B_KEY}").status_code == 200
        browse_b = c.get(f"/d/{B_KEY}/browse/company")
        assert browse_b.status_code == 200
        assert "iso-unit" not in browse_b.text
        # A's unit addressed through B's path: kernel pin -> honest 404.
        unit404 = c.get(f"/d/{B_KEY}/units/company/iso-unit")
        assert unit404.status_code == 404
        assert unit404.json()["detail"] == "unit not found"

        # A's task id through B's path: 404, no leak, no state change.
        r = c.post(
            f"/d/{B_KEY}/tasks/{task_a['id']}/status",
            data={"to_status": "done"}, follow_redirects=False,
        )
    assert r.status_code == 404
    assert r.json()["detail"] == "task not found"

    after = bench_authoring.authoring_get_task(seeded_db, task_id=task_a["id"])
    assert after["status"] == "pending" and len(after["transitions"]) == 1


def test_assignee_select_lists_only_this_domains_members(seeded_db):
    """向域内成员指派: the lead's form is a select over THIS domain's active
    memberships — alice/rae/lara render as options, B's member does not."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as c:
        r = c.get(f"/d/{A_KEY}/tasks/new")
    assert r.status_code == 200
    assert 'value="alice"' in r.text
    assert 'value="rae"' in r.text
    assert 'value="lara"' in r.text
    assert "bob" not in r.text  # the other domain's member is absent entirely


# =========================================================================== #
# 导航 (base.html 「我的域」 per-domain workbench links)                         #
# =========================================================================== #


def test_nav_workbench_links_follow_membership_and_admin_gate(seeded_db):
    """导航按域过滤 (C5 域优先): the chrome carries ONE 「我的域」 entry → /d,
    never a per-domain link list; a member sees it, a membership-less admin
    does not (and sees the 管理门 links instead). Another domain's key or name
    never leaks into the chrome."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("alice", _READ_WRITE)) as c:
        r = c.get("/rubrics")
    assert r.status_code == 200
    assert '>我的域</a>' in r.text                      # the one domain door
    assert 'href="/d"' in r.text                        # ... pointing at /d
    assert f"/d/{B_KEY}" not in r.text          # non-member domain: nothing
    assert B_KEY not in r.text and DOMAIN_B_NAME not in r.text

    with _client(seeded_db, _user("admin-u", ["*"])) as c:
        r = c.get("/admin/templates")
    assert r.status_code == 200
    assert 'class="muted">管理门' in r.text
    assert '/admin/templates"' in r.text
    assert '/admin/domains"' in r.text
    assert "/d/" not in r.text                  # no membership -> no domain links
    assert '>我的域</a>' not in r.text                  # no membership -> no door
    # Brand + the 「全域」 estate entry: the estate console is a platform-level
    # surface (content:read), so it shows even without a membership — while the
    # 「我的域」 door stays membership-only (asserted above).
    assert r.text.count('href="/d"') == 2
    assert DOMAIN_A_NAME not in r.text and DOMAIN_B_NAME not in r.text
