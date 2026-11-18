"""Web tests for the domain-first console (change ``add-domain-first-workbench``).

Covers the P0 surfaces over HTTP only — the door (``/d``), the six domain areas,
the composition of the two gates (platform scope ▶ domain role), and the three
read projections the console adds (ledger, inbox, bench shelf):

* ``domain-console`` — 登录落点与我的域列表 / 域上下文常驻与切换 / 域内六区导航
  与角色渲染 / 平台门与域内导航分离 / 落点互认与旧链接兼容.
* ``domain-ontology-ledger`` — 四层台账一页对齐 / 诚实空态 / 一致性核对 /
  发布层 digest 单源 / 消费层只读 / 域边界.
* ``domain-proposal-inbox`` — 入箱携带依据 / 确认经内核落库 / 驳回退回且同键不
  自动重提 / 角色权限 / 待确认计数.
* ``domain-bench-catalog`` — 归属登记 / 列示与操作 / 未归属池 / 不影响评测执行.

World: the same single-template world the authoring suite builds — domain A
``aw-key`` (alice=expert, rae=annotator, lara=lead), domain B ``bw-key`` (bob=
expert), one throwaway template. The kernel has no physical-delete API, so the
seeded namespaces are cleared explicitly and every test starts from an empty
ontology regardless of order.

Assertions anchor on rendered MARKUP and on values that exist only in seeded
data — every catalog string also rides the ``window.__LOCALE__`` bootstrap, so a
bare zh string is not proof that a page rendered it.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qs, quote, urlparse

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.bench import authoring as bench_authoring
from src.bench import distribution as bench_distribution
from src.bench import templates as bench_templates
from src.bench import workspaces
from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user
from src.web.deps import get_db

VALID_SCHEMA = {
    "entity_types": ["company", "indicator"],
    "concept_structures": {"indicator": ["name", "unit"]},
    "relationship_kinds": ["belongs_to"],
    "tier_vocabulary": ["gold", "silver", "bronze", "raw"],
    "sensitivity_vocabulary": ["public", "internal", "confidential"],
    "corpus_declaration": {"source_types": []},
}

DOMAIN_A_NAME = "甲域"
DOMAIN_B_NAME = "乙域"
A_KEY = "aw-key"
B_KEY = "bw-key"

_READ_WRITE = ["content:read", "content:write"]


# --- seed + client helpers -------------------------------------------------- #


def _seed_world(conn) -> dict:
    """One template, two domains; A: alice=expert rae=annotator lara=lead, B: bob."""
    for table in (
        "domain_proposals",
        "domain_proposal_events",
        "domain_assets",
        "distribution_pull_events",
        "ontology_publications",
        "distribution_consumers",
    ):
        conn.execute(f"DELETE FROM {table}")
    conn.execute(
        "DELETE FROM knowledge_units WHERE namespace IN (%s, %s)", (A_KEY, B_KEY)
    )
    conn.commit()
    bench_templates.create_template(
        conn, name="console-template", schema=dict(VALID_SCHEMA), created_by="seed"
    )
    a = workspaces.instantiate_domain(
        conn, key=A_KEY, name=DOMAIN_A_NAME,
        template_name="console-template", template_version=None, created_by="seed",
    )
    b = workspaces.instantiate_domain(
        conn, key=B_KEY, name=DOMAIN_B_NAME,
        template_name="console-template", template_version=None, created_by="seed",
    )
    # instantiate_domain may reuse a domain from an earlier test run; members and
    # assets are cleared so the world stays identical. Membership is append-only
    # history, so a revoke marks the old row inactive rather than deleting it.
    for domain in (a, b):
        for member in workspaces.list_members(conn, domain_id=domain["id"]):
            if member.get("active", True) is not False:
                try:
                    workspaces.remove_member(
                        conn, domain_id=domain["id"], user_id=member["user_id"]
                    )
                except Exception:
                    pass
    workspaces.add_member(conn, domain_id=a["id"], user_id="alice", role="expert", added_by="seed")
    workspaces.add_member(conn, domain_id=a["id"], user_id="rae", role="annotator", added_by="seed")
    workspaces.add_member(conn, domain_id=a["id"], user_id="lara", role="lead", added_by="seed")
    workspaces.add_member(conn, domain_id=b["id"], user_id="bob", role="expert", added_by="seed")
    return {"a": a, "b": b}


def _user(sub: str, scopes: list[str]) -> User:
    return User(
        sub=sub, name=sub, email=f"{sub}@example.com",
        scopes=list(scopes), channel="test",
    )


def _client(db, user: User) -> TestClient:
    """App with ``get_db`` + ``get_current_user`` overridden to ``user``."""
    app = create_app()

    def _current_user(request: Request) -> User:
        request.state.user = user
        return user

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _current_user
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_idp(monkeypatch):
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)


def _params(location: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}


def _rendered(html: str) -> str:
    """HTML 去掉 i18n 引导脚本。

    页面里嵌着整份 `window.__LOCALE__`，所以一个裸中文串**不能**证明页面渲染了
    它——它可能在引导脚本里。判「这一句出现在页面上」必须先去掉那份脚本。
    """
    return re.sub(r"<script>window\.__LOCALE__.*?</script>", "", html, flags=re.S)


# =========================================================================== #
# 门：/ 与 /d 与旧链接                                                        #
# =========================================================================== #


def test_root_redirects_to_the_domain_door(seeded_db):
    """``/`` no longer dumps everyone into the legal rubric list."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("alice", _READ_WRITE)) as c:
        r = c.get("/", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/d"


def test_domain_list_shows_only_my_domains_with_my_role(seeded_db):
    """One row per active membership, with the role I hold THERE (not a global role)."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as c:
        r = c.get("/d")
    assert r.status_code == 200
    assert DOMAIN_A_NAME in r.text and A_KEY in r.text
    # Neutral badge: harbor purple marks the PLATFORM admin identity only, never
    # a domain role (a domain lead is a role inside a domain, not a platform tier).
    assert '<span class="badge">负责人</span>' in r.text   # lead on A
    assert DOMAIN_B_NAME not in r.text and B_KEY not in r.text     # non-member
    assert f"/d/{A_KEY}" in r.text                                 # the open link


def test_domain_list_empty_state_is_honest_and_role_aware(seeded_db):
    """No membership → no domain inventing: a plain "wait for an invitation";
    a platform admin additionally gets the platform gate link (never a domain)."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("nobody", _READ_WRITE)) as c:
        r = c.get("/d")
    assert r.status_code == 200
    assert DOMAIN_A_NAME not in r.text and DOMAIN_B_NAME not in r.text
    assert "/admin/domains" not in r.text        # not an admin: no platform gate

    with _client(seeded_db, _user("admin-u", ["*"])) as c:
        r = c.get("/d")
    assert r.status_code == 200
    # An admin's visible range is the whole estate (add-domain-tree-and-shared-
    # libraries §4.2): the gap matrix is the page, and it is empty for the only
    # role that can act on the gaps if memberships were required to see it.
    assert DOMAIN_A_NAME in r.text and DOMAIN_B_NAME in r.text
    assert "/admin/domains" in r.text            # the platform gate stays available


def test_non_member_is_denied_with_the_domain_gate_not_a_disguised_404(seeded_db):
    """rala holds content:* but no membership in B: the DOMAIN gate refuses her,
    and the refusal leaks nothing about B in the body."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("alice", _READ_WRITE)) as c:
        r = c.get(f"/d/{B_KEY}")
    assert r.status_code == 403
    assert r.json()["detail"] == "无该域权限"
    assert DOMAIN_B_NAME not in r.text


def test_legacy_workbench_home_redirects_to_the_domain_home(seeded_db):
    """旧链接兼容: ``/workbench/{key}`` is 302 → ``/d/{key}``; the gates still run
    first, so a non-member gets 403 and never a redirect."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("alice", _READ_WRITE)) as c:
        r = c.get(f"/workbench/{A_KEY}", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == f"/d/{A_KEY}"
        followed = c.get(f"/workbench/{A_KEY}")
        assert followed.status_code == 200
        assert '<h2>我的任务</h2>' in followed.text

        denied = c.get(f"/workbench/{B_KEY}", follow_redirects=False)
    assert denied.status_code == 403


def test_legacy_deep_link_redirects_with_its_key_and_query_intact(seeded_db):
    """A bookmarked *authoring* deep link survives the prefix move.

    Authoring route params are percent-encoded because unit keys carry ``->``
    and ``:`` (``ai-corp->belongs_to:acme``). The compatibility hop must hand
    the same key and the same query string to ``/d/…`` — a re-encoded or
    truncated key would 404 a link that used to work.
    """
    _seed_world(seeded_db)
    key = quote("ai-corp->belongs_to:acme", safe="")
    with _client(seeded_db, _user("alice", _READ_WRITE)) as c:
        r = c.get(
            f"/workbench/{A_KEY}/units/belongs_to/{key}?limit=5",
            follow_redirects=False,
        )
    assert r.status_code == 302
    assert r.headers["location"] == f"/d/{A_KEY}/units/belongs_to/{key}?limit=5"


def test_domain_switcher_lists_exactly_my_domains(seeded_db):
    """The switcher is server-resolved from membership — bob's chrome offers B and
    never A, and the current domain is the one in the path."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("bob", _READ_WRITE)) as c:
        r = c.get(f"/d/{B_KEY}")
    assert r.status_code == 200
    assert DOMAIN_B_NAME in r.text
    assert DOMAIN_A_NAME not in r.text and A_KEY not in r.text


# =========================================================================== #
# 六区导航与角色渲染                                                          #
# =========================================================================== #


#: The seven areas every member sees; ``settings`` is lead-only.
MEMBER_AREAS = ("ontology", "knowledge", "eval-standards", "eval-runs", "inbox", "publish")


def test_annotator_sees_member_areas_and_no_settings(seeded_db):
    """annotator: read every area except settings (lead-only).

    ``bench`` became ``eval-runs`` when evaluation standards got their own area
    (add-domain-tree-and-shared-libraries §4); the old URL 302s, so it must not
    appear in the nav any more.
    """
    _seed_world(seeded_db)
    with _client(seeded_db, _user("rae", _READ_WRITE)) as c:
        r = c.get(f"/d/{A_KEY}")
        assert r.status_code == 200
        assert 'class="zone-nav"' in r.text
        for area in MEMBER_AREAS:
            assert f"/d/{A_KEY}/{area}" in r.text
        assert f"/d/{A_KEY}/settings" not in r.text
        assert f"/d/{A_KEY}/bench" not in r.text, "legacy bench must not be offered as an area"

        settings = c.get(f"/d/{A_KEY}/settings")
        legacy = c.get(f"/d/{A_KEY}/bench", follow_redirects=False)
    assert settings.status_code == 403
    assert legacy.status_code == 302
    assert legacy.headers["location"].endswith(f"/d/{A_KEY}/eval-runs")


def test_lead_sees_settings(seeded_db):
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as c:
        r = c.get(f"/d/{A_KEY}")
        assert f"/d/{A_KEY}/settings" in r.text
        s = c.get(f"/d/{A_KEY}/settings")
    assert s.status_code == 200
    assert "alice" in s.text and "rae" in s.text


def test_platform_admin_without_membership_reaches_every_area(seeded_db):
    """Platform admin bypasses the domain role check (四级角色): all six areas,
    and never a member-only string from another domain."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("root", ["*"])) as c:
        r = c.get(f"/d/{A_KEY}")
        assert r.status_code == 200
        for area in (*MEMBER_AREAS, "settings"):
            assert f"/d/{A_KEY}/{area}" in r.text
        assert '<span class="badge">管理员</span>' in r.text
        s = c.get(f"/d/{A_KEY}/settings")
    assert s.status_code == 200
    assert DOMAIN_B_NAME not in s.text


def test_platform_gate_lives_outside_a_domain_area(seeded_db):
    """The 管理门 entries are platform chrome: they must not be repeated inside a
    domain page (that is the conflation C5 removes)."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("root", ["*"])) as c:
        r = c.get(f"/d/{A_KEY}")
    assert r.status_code == 200
    assert "/admin/domains" in r.text        # still reachable from the chrome
    assert 'class="zone-nav"' in r.text
    # ... but not offered as a domain area.
    assert f"/d/{A_KEY}/admin" not in r.text


# =========================================================================== #
# 本体台账（四层 + 空态 + digest 单源）                                       #
# =========================================================================== #


def test_ledger_shows_all_four_layers_even_when_empty(seeded_db):
    """A missing layer is reported with its own source table and next step —
    never hidden, never collapsed."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("alice", _READ_WRITE)) as c:
        r = c.get(f"/d/{A_KEY}/ontology")
    assert r.status_code == 200
    for heading in ("声明层", "策展层", "发布层", "消费层"):
        assert f"<h2>{heading}</h2>" in r.text
    # Honest empties: no publication, no consumers, no units.
    assert "尚无发布" in r.text
    assert "尚无登记消费者" in r.text
    assert "knowledge_units" in r.text and "ontology_publications" in r.text
    # Declared vocabulary is rendered from the anchored template.
    assert "company" in r.text and "belongs_to" in r.text


def test_ledger_digest_is_the_published_digest_verbatim(seeded_db):
    """Single source: the page shows the digest stored in ``ontology_publications``
    and the pull surface serves the same one — the ledger never recomputes it."""
    world = _seed_world(seeded_db)
    bench_authoring.authoring_create_unit(
        seeded_db, domain_key=A_KEY, kind="company", external_key="ai-corp",
        body="人工智能公司条目", operator="alice",
    )
    publication = bench_distribution.publish_domain(
        seeded_db, domain_key=A_KEY, published_by="lara"
    )
    token = "console-test-token"
    bench_distribution.register_consumer(
        seeded_db, name="pull-probe",
        domains=[A_KEY],
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        created_by="seed",
    )

    with _client(seeded_db, _user("alice", _READ_WRITE)) as c:
        page = c.get(f"/d/{A_KEY}/ontology")
        pull = c.get(
            f"/api/v1/distribution/{A_KEY}/ontology",
            headers={"X-Consumer-Token": token},
        )
    assert page.status_code == 200
    assert pull.status_code == 200
    assert publication["digest"] in page.text
    assert pull.json()["digest"] == publication["digest"]
    # Version is rendered as v{n}, and history exists once there is more than one.
    assert f"v{publication['version']}" in page.text
    assert world["a"]["key"] == A_KEY


def test_ledger_curation_layer_offers_authoring_entries_by_role(seeded_db):
    """The curation layer is the authoring ACTION surface: browse for readers,
    create for experts; an out-of-vocabulary kind never offers create (the form
    would 404 on the vocabulary gate)."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("alice", _READ_WRITE)) as c:
        r = c.get(f"/d/{A_KEY}/ontology")
    assert r.status_code == 200
    assert f"/d/{A_KEY}/browse/company" in r.text
    assert f"/d/{A_KEY}/units/company/new" in r.text

    with _client(seeded_db, _user("rae", _READ_WRITE)) as c:
        r = c.get(f"/d/{A_KEY}/ontology")
    assert r.status_code == 200
    assert f"/d/{A_KEY}/browse/company" in r.text
    assert f"/d/{A_KEY}/units/company/new" not in r.text   # write gate


# =========================================================================== #
# 提案箱                                                                      #
# =========================================================================== #


def _submit(c: TestClient, *, key: str, evidence: dict, kind: str = "company",
            domain_key: str = A_KEY, as_user: str = "alice",
            source: str | None = None) -> dict:
    """Submit as ``as_user`` — the caller may only claim its own identity."""
    source = source or f"user:{as_user}@example.com"
    r = c.post(
        f"/api/d/{domain_key}/proposals",
        json={
            "source": source, "kind": kind, "external_key": key,
            "body": f"{key} 的条目正文", "evidence": evidence,
            "impact": "将新增一条实体",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "created" in body, "the submit response must say new vs idempotent hit"
    return body


def test_inbox_confirm_writes_through_the_kernel(seeded_db):
    """expert submits, lead confirms: the unit lands in the domain namespace and
    the proposal records the decision — one kernel path, one event trail."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("alice", _READ_WRITE)) as c:
        proposal = _submit(c, key="ai-corp", evidence={"url": "https://example.test/a"})
        assert proposal["created"] is True
        repeat = _submit(c, key="ai-corp", evidence={"url": "https://example.test/a"})
        assert repeat["created"] is False, "a repeat submission is an idempotent hit"
        assert repeat["id"] == proposal["id"]
    with _client(seeded_db, _user("lara", _READ_WRITE)) as c:
        inbox = c.get(f"/d/{A_KEY}/inbox")
        assert inbox.status_code == 200
        assert "ai-corp" in inbox.text
        assert "user:alice" in inbox.text
        confirm = c.post(
            f"/d/{A_KEY}/inbox/{proposal['id']}/confirm", follow_redirects=False
        )
    assert confirm.status_code == 303
    assert _params(confirm.headers["location"])["msg"] == "console.flash.proposal_confirmed"

    units = bench_authoring.authoring_list_units(
        seeded_db, domain_key=A_KEY, kind="company"
    )
    assert [u["external_key"] for u in units] == ["ai-corp"]


def test_inbox_forbids_self_confirmation(seeded_db):
    """A lead who submitted the draft cannot also approve it (separation of
    duties); the platform admin may, but only with the override recorded."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as c:
        proposal = _submit(c, key="self-serv", evidence={"url": "https://example.test/s"},
                           as_user="lara")
        denied = c.post(
            f"/d/{A_KEY}/inbox/{proposal['id']}/confirm", follow_redirects=False
        )
    assert denied.status_code == 303
    params = _params(denied.headers["location"])
    assert params["msg"] == "console.flash.proposal_failed"
    assert "提案人不得自提自确认" in params["detail"]
    assert bench_authoring.authoring_list_units(
        seeded_db, domain_key=A_KEY, kind="company"
    ) == []


def test_inbox_reject_requires_a_reason_and_blocks_identical_resubmission(seeded_db):
    """A rejection is only actionable with a reason, and re-sending the SAME
    evidence is refused — the submitter must bring something new."""
    _seed_world(seeded_db)
    evidence = {"url": "https://example.test/r"}
    with _client(seeded_db, _user("alice", _READ_WRITE)) as c:
        proposal = _submit(c, key="weak-source", evidence=evidence)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as c:
        bare = c.post(
            f"/d/{A_KEY}/inbox/{proposal['id']}/reject",
            data={"note": "   "}, follow_redirects=False,
        )
        assert bare.status_code == 303
        params = _params(bare.headers["location"])
        assert params["msg"] == "console.flash.proposal_failed"
        assert "驳回必须写明理由" in params["detail"]

        rejected = c.post(
            f"/d/{A_KEY}/inbox/{proposal['id']}/reject",
            data={"note": "来源不可核验"}, follow_redirects=False,
        )
    assert rejected.status_code == 303
    assert _params(rejected.headers["location"])["msg"] == "console.flash.proposal_rejected"

    with _client(seeded_db, _user("alice", _READ_WRITE)) as c:
        same = c.post(
            f"/api/d/{A_KEY}/proposals",
            json={
                "source": "user:alice@example.com", "kind": "company", "external_key": "weak-source",
                "body": "同一条目再提", "evidence": evidence,
            },
        )
        assert same.status_code == 400
        assert "同键已驳回，需新证据" in same.json()["detail"]

        fresh = _submit(c, key="weak-source", evidence={"url": "https://example.test/r2"})
    assert fresh["state"] == "pending"


def test_inbox_requires_evidence_at_the_edge(seeded_db):
    """A draft with no evidence behind it is refused at submission (the inbox is
    a queue of checkable claims, not a wish list)."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("alice", _READ_WRITE)) as c:
        r = c.post(
            f"/api/d/{A_KEY}/proposals",
            json={
                "source": "user:alice@example.com", "kind": "company", "external_key": "no-proof",
                "body": "没有依据的条目", "evidence": {},
            },
        )
    assert r.status_code == 400
    assert "提案必须携带依据" in r.json()["detail"]


def test_inbox_is_domain_scoped(seeded_db):
    """Another domain's reviewer cannot decide this domain's proposal, and the
    inbox of a domain I am not a member of is 403 — not an empty list."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("alice", _READ_WRITE)) as c:
        proposal = _submit(c, key="scoped", evidence={"url": "https://example.test/x"})
    with _client(seeded_db, _user("bob", _READ_WRITE)) as c:
        foreign = c.get(f"/d/{A_KEY}/inbox")
        decide = c.post(
            f"/d/{A_KEY}/inbox/{proposal['id']}/confirm", follow_redirects=False
        )
    assert foreign.status_code == 403
    assert decide.status_code == 403
    assert bench_authoring.authoring_list_units(
        seeded_db, domain_key=A_KEY, kind="company"
    ) == []


def test_pending_count_on_the_overview_matches_the_inbox(seeded_db):
    """总览的待确认数与提案箱一致 — both read the same table."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("alice", _READ_WRITE)) as c:
        _submit(c, key="one", evidence={"url": "https://example.test/1"})
        _submit(c, key="two", evidence={"url": "https://example.test/2"})
        overview = c.get(f"/d/{A_KEY}")
        inbox = c.get(f"/d/{A_KEY}/inbox?state=pending")
    assert overview.status_code == 200 and inbox.status_code == 200
    assert '<div class="stat-value">2</div>' in overview.text
    assert "one" in inbox.text and "two" in inbox.text


# =========================================================================== #
# 发布与消费                                                                  #
# =========================================================================== #


def test_publish_action_freezes_a_version_and_shows_its_footprint(seeded_db):
    """The lead publishes from the console through the existing publish function;
    the machine pull then leaves an append-only footprint (消费层)."""
    _seed_world(seeded_db)
    bench_authoring.authoring_create_unit(
        seeded_db, domain_key=A_KEY, kind="company", external_key="acme",
        body="条目", operator="alice",
    )
    with _client(seeded_db, _user("lara", _READ_WRITE)) as c:
        r = c.post(f"/d/{A_KEY}/publish", follow_redirects=False)
        assert r.status_code == 303
        params = _params(r.headers["location"])
        assert params["msg"] == "console.flash.published"
        assert params["version"] == "1"

        page = c.get(f"/d/{A_KEY}/publish")
    assert page.status_code == 200
    assert "v1" in page.text

    token = "footprint-token"
    bench_distribution.register_consumer(
        seeded_db, name="footprint-probe", domains=[A_KEY],
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        created_by="seed",
    )
    with _client(seeded_db, _user("lara", _READ_WRITE)) as c:
        pull = c.get(
            f"/api/v1/distribution/{A_KEY}/ontology",
            headers={"X-Consumer-Token": token},
        )
        assert pull.status_code == 200
        page = c.get(f"/d/{A_KEY}/publish")
    assert page.status_code == 200
    assert "footprint-probe" in page.text
    # The last-pull cell renders "v{n} · {timestamp}"; the never-pulled label is a
    # catalog string and therefore also present in the locale bootstrap, so it
    # cannot serve as a negative assertion.
    assert f"v{pull.json()['publication_version']} · " in page.text


def test_expert_cannot_publish(seeded_db):
    """Publishing is lead work: an expert's POST is refused by the role gate."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("alice", _READ_WRITE)) as c:
        r = c.post(f"/d/{A_KEY}/publish", follow_redirects=False)
    assert r.status_code == 403
    assert bench_distribution.list_publications(seeded_db, domain_key=A_KEY) == []


# =========================================================================== #
# 评测资产目录                                                                #
# =========================================================================== #


def test_bench_shelf_assign_list_and_unassign(seeded_db):
    """归属是目录: assign adds one directory row, the page lists it under its
    kind, unassign removes the row — the asset itself is never touched."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as c:
        r = c.post(
            f"/d/{A_KEY}/bench/assign",
            data={"asset_kind": "prompt", "asset_key": "some-prompt"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert _params(r.headers["location"])["msg"] == "console.flash.asset_assigned"

        page = c.get(f"/d/{A_KEY}/bench")
        assert page.status_code == 200
        assert "some-prompt" in page.text
        assert "孤立" in page.text or "已删除" in page.text   # orphan is labelled

        gone = c.post(
            f"/d/{A_KEY}/bench/unassign",
            data={"asset_kind": "prompt", "asset_key": "some-prompt"},
            follow_redirects=False,
        )
        assert gone.status_code == 303
        after = c.get(f"/d/{A_KEY}/bench")
    assert "some-prompt" not in after.text


def test_bench_shelf_never_changes_evaluation_behaviour(seeded_db):
    """The shelf is a console concern: the kind vocabulary and the engine's own
    tables are untouched by an assignment."""
    _seed_world(seeded_db)
    before = seeded_db.execute("SELECT COUNT(*) AS n FROM prompts").fetchone()["n"]
    with _client(seeded_db, _user("lara", _READ_WRITE)) as c:
        c.post(
            f"/d/{A_KEY}/bench/assign",
            data={"asset_kind": "prompt", "asset_key": "eval-prompt"},
        )
    after = seeded_db.execute("SELECT COUNT(*) AS n FROM prompts").fetchone()["n"]
    assert after == before


def test_annotator_cannot_catalog_assets(seeded_db):
    """Cataloging is lead work (it decides what the domain's shelf claims)."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("rae", _READ_WRITE)) as c:
        r = c.post(
            f"/d/{A_KEY}/bench/assign",
            data={"asset_kind": "prompt", "asset_key": "nope"},
            follow_redirects=False,
        )
    assert r.status_code == 403


# =========================================================================== #
# 4.3 兼容表：既有路径逐条可达，权限判定不变                                    #
# =========================================================================== #


_LEGACY_MEMBER_PATHS = (
    "/rubrics",
    "/prompts",
    "/compare",
    "/samples",
    "/clauses",
    "/law-info",
    "/law-references",
    "/contracts",
    "/review",
    "/search",
    "/dashboard",
)

_LEGACY_ADMIN_PATHS = (
    "/admin/templates",
    "/admin/domains",
)


def test_every_legacy_path_still_resolves_for_a_member(seeded_db):
    """The console is additive: every pre-existing page keeps its own route, its
    own template and its own permission judgment. This walks the compatibility
    table — a 404 or 500 here means the door change broke a real page."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("alice", _READ_WRITE)) as c:
        statuses = {path: c.get(path).status_code for path in _LEGACY_MEMBER_PATHS}
        workbench = c.get(f"/workbench/{A_KEY}", follow_redirects=False).status_code
        admin = {path: c.get(path).status_code for path in _LEGACY_ADMIN_PATHS}
    assert {p: s for p, s in statuses.items() if s >= 400} == {}
    assert workbench == 302
    # Admin pages stay platform-admin exclusive for a domain expert.
    assert set(admin.values()) == {403}


def test_every_legacy_path_still_resolves_for_a_platform_admin(seeded_db):
    """...and the platform gate keeps working: the same admin paths 200 for an
    admin identity, with the domain pages untouched by that scope."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("root", ["*"])) as c:
        admin = {path: c.get(path).status_code for path in _LEGACY_ADMIN_PATHS}
        domain_admin = c.get(f"/admin/domains/{A_KEY}").status_code
    assert set(admin.values()) == {200}
    assert domain_admin == 200


# =========================================================================== #
# 结局回流与迁移计数（add-fleet-execution-loop §4 / §2.4）                      #
# =========================================================================== #


def test_outcomes_are_readable_only_by_their_own_submitter(seeded_db):
    """A submitter reads how its draft ended — and cannot read anyone else's.

    ``alice`` files as herself; ``bob`` asks for alice's source and must be
    refused, because the route authorizes the *claimed* source against the
    caller's identity instead of trusting the query string.
    """
    _seed_world(seeded_db)
    with _client(seeded_db, _user("alice", _READ_WRITE)) as c:
        proposal = _submit(c, key="outcome-1", evidence={"url": "https://example.test/o"})
    # Rejection is a lead act; the submitter and the judge are different people.
    with _client(seeded_db, _user("lara", _READ_WRITE)) as c:
        reject = c.post(
            f"/d/{A_KEY}/inbox/{proposal['id']}/reject",
            data={"note": "依据无法回源"}, follow_redirects=False,
        )
        assert reject.status_code == 303
    with _client(seeded_db, _user("alice", _READ_WRITE)) as c:
        mine = c.get(f"/api/d/{A_KEY}/proposals/outcomes",
                     params={"source": "user:alice@example.com"})
    assert mine.status_code == 200, mine.text
    rows = mine.json()["outcomes"]
    assert len(rows) == 1
    assert rows[0]["state"] == "rejected"
    assert rows[0]["decision_note"] == "依据无法回源"

    with _client(seeded_db, _user("bob", _READ_WRITE)) as c:
        theirs = c.get(f"/api/d/{A_KEY}/proposals/outcomes",
                       params={"source": "user:alice@example.com"})
    assert theirs.status_code == 403
    assert "只能读取自己来源" in theirs.json()["detail"]


def test_legacy_counts_are_admin_only(seeded_db):
    _seed_world(seeded_db)
    with _client(seeded_db, _user("alice", _READ_WRITE)) as c:
        denied = c.get("/api/v1/distribution/legacy-sources")
    assert denied.status_code == 403

    with _client(seeded_db, _user("root", ["*"])) as c:
        allowed = c.get("/api/v1/distribution/legacy-sources")
    assert allowed.status_code == 200
    body = allowed.json()
    assert body["mode"] in ("strict", "lenient")
    assert "sources" in body


# --- §2.6b 来自真实 HTTP 路由的提交方判定 ------------------------------------- #
# 函数级测试已经覆盖九类结论，但路由是**另一处**必须传对 ``via`` 的地方：传错等于
# 没有校验，而函数级的绿完全看不出来。所以这一节只用真请求，不碰判定函数。


def _post(c, *, source, key, domain_key=A_KEY):
    return c.post(
        f"/api/d/{domain_key}/proposals",
        json={
            "source": source, "kind": "company", "external_key": key,
            "body": f"{key} 正文", "evidence": {"url": f"https://example.test/{key}"},
        },
    )


def test_http_call_cannot_claim_an_extract_source(seeded_db):
    """``extract:`` 的信任前提是「管线从网络不可达」；公网面必须当场否掉。"""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("alice", _READ_WRITE)) as c:
        r = _post(c, source="extract:qwen:2025-10", key="impersonated")
    assert r.status_code == 403, r.text
    assert "进程内" in r.json()["detail"]

    written = seeded_db.execute(
        "SELECT count(*) AS n FROM domain_proposals WHERE external_key = 'impersonated'"
    ).fetchone()["n"]
    assert written == 0, "被拒的冒充不能留下半行"


def test_http_call_from_an_unregistered_fleet_is_refused(seeded_db):
    _seed_world(seeded_db)
    with _client(seeded_db, _user("alice", _READ_WRITE)) as c:
        r = _post(c, source="fleet:fleet_nobody/post_1", key="stranger")
    assert r.status_code == 403
    assert "未登记" in r.json()["detail"]


def test_http_call_from_a_registered_fleet_is_accepted(seeded_db):
    _seed_world(seeded_db)
    bench_distribution.register_consumer(
        seeded_db, name="ontology-fleet", domains=[A_KEY],
        token_hash=hashlib.sha256(b"tok").hexdigest(), created_by="seed",
        kind="fleet", fleet_ref="fleet_a",
    )
    with _client(seeded_db, _user("alice", _READ_WRITE)) as c:
        ok = _post(c, source="fleet:fleet_a/post_1", key="from-fleet")
    assert ok.status_code == 200, ok.text
    assert ok.json()["created"] is True

    # 登记绑域：同一个 fleet_ref 在别人域里仍是未登记。这里必须换成 B 域自己的
    # 成员来发——拿 A 域的人去发会先被域权限门（403「无该域权限」）挡掉，那样
    # 测到的是门，不是绑域。
    with _client(seeded_db, _user("bob", _READ_WRITE)) as c:
        cross = _post(c, source="fleet:fleet_a/post_1", key="cross", domain_key=B_KEY)
    assert cross.status_code == 403
    # 说不成「未登记」：这个 fleet_ref 确实登记过，错的是域。结论要指对原因，
    # 否则运维会去重新登记一个已经存在的舰队。
    assert "域不在绑定范围" in cross.json()["detail"]


def test_http_call_cannot_claim_another_persons_identity(seeded_db):
    _seed_world(seeded_db)
    with _client(seeded_db, _user("alice", _READ_WRITE)) as c:
        r = _post(c, source="user:bob@example.com", key="stolen-identity")
    assert r.status_code == 403
    assert "只能以自己的身份提交" in r.json()["detail"]

    # 正例在 bob 自己的域里做（在 A 域他连门都过不去，测不到身份判定）。
    with _client(seeded_db, _user("bob", _READ_WRITE)) as c:
        own = _post(c, source="user:bob@example.com", key="own-identity", domain_key=B_KEY)
    assert own.status_code == 200, own.text


# =========================================================================== #
# 工单 / 派单 / 台账的来源：三档后果必须分开说                                 #
# =========================================================================== #


def _task(seeded_db, domain, **kw):
    params = dict(
        domain_id=domain["id"], assignee="alice", title="t", detail="d",
        target_kind="estate-gap", target_key="ontology", created_by="lara",
    )
    params.update(kw)
    return bench_authoring.authoring_create_task(seeded_db, **params)


def test_work_orders_page_shows_all_three_kinds(seeded_db):
    """总览的「我的任务」只匹配人；另外两档必须还有一页能看见，否则它们无法关闭。"""
    world = _seed_world(seeded_db)
    _task(seeded_db, world["a"], assignee="alice@example.com")
    _task(seeded_db, world["a"], assignee="agent:builder@aw-key",
          assignee_kind="kernel-role", assignee_ref="builder", target_key="knowledge")
    bench_distribution.register_consumer(
        seeded_db, name="ontology-fleet", domains=[A_KEY],
        token_hash=hashlib.sha256(b"t").hexdigest(), created_by="seed",
        kind="fleet", fleet_ref="fleet_a",
    )
    _task(seeded_db, world["a"], assignee="ontology-fleet",
          assignee_kind="fleet", assignee_ref="fleet_a", target_key="eval")

    with _client(seeded_db, _user("lara", _READ_WRITE)) as c:
        page = c.get(f"/d/{A_KEY}/work-orders")
    body = _rendered(page.text)
    assert page.status_code == 200, page.text
    assert "ontology-fleet" in body
    assert "<code>builder</code>" in body
    # 三档各一句后果：共用一句「已派出」会把「等舰队认领」说成「下一轮就跑」。
    assert "内核岗位下一轮执行" in body
    assert "等待舰队认领" in body
    assert "由人处理" in body


def test_work_orders_can_be_filtered_by_kind_and_status(seeded_db):
    world = _seed_world(seeded_db)
    _task(seeded_db, world["a"], assignee="alice@example.com", target_key="ontology")
    _task(seeded_db, world["a"], assignee="agent:builder@aw-key",
          assignee_kind="kernel-role", assignee_ref="builder", target_key="knowledge")

    with _client(seeded_db, _user("lara", _READ_WRITE)) as c:
        only_role = c.get(f"/d/{A_KEY}/work-orders", params={"kind": "kernel-role"})
        only_human = c.get(f"/d/{A_KEY}/work-orders", params={"kind": "human"})
        bad = c.get(f"/d/{A_KEY}/work-orders", params={"kind": "robot"})
    role_body, human_body = _rendered(only_role.text), _rendered(only_human.text)
    assert "<code>builder</code>" in role_body
    assert "alice@example.com" not in role_body
    assert "alice@example.com" in human_body
    assert "<code>builder</code>" not in human_body
    assert bad.status_code == 422


def test_work_orders_is_empty_honestly_when_there_are_none(seeded_db):
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as c:
        page = c.get(f"/d/{A_KEY}/work-orders")
    assert page.status_code == 200
    assert "本域没有工单" in _rendered(page.text)


def test_work_orders_is_domain_scoped(seeded_db):
    _seed_world(seeded_db)
    with _client(seeded_db, _user("bob", _READ_WRITE)) as c:
        assert c.get(f"/d/{B_KEY}/work-orders").status_code == 200
        assert c.get(f"/d/{A_KEY}/work-orders").status_code == 403


def test_dispatch_page_offers_the_route_table_role(seeded_db):
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as c:
        page = c.get("/d/dispatch", params={"gap": "ontology"})
    assert page.status_code == 200, page.text
    body = _rendered(page.text)
    assert "kernel:builder" in body
    # 选择器存在，且默认选项就是分诊表指定的那个岗位。
    assert 'name="assignee_kind"' in body
    assert "下一轮执行" in body


def test_dispatch_page_refuses_to_offer_agents_for_a_human_gap(seeded_db):
    """归人的缺口只有一档可选：给智能体选项等于让人以为它能替人做复核。"""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as c:
        page = c.get("/d/dispatch", params={"gap": "quality:review_lag"})
    assert page.status_code == 200, page.text
    body = _rendered(page.text)
    assert "这个缺口归人" in body
    # 判据是「没有智能体可选项」：这个缺口下没有任何 domain 会给出 fleet/岗位按钮。
    assert 'value="fleet"' not in body
    assert 'value="kernel-role"' not in body


def test_dispatch_page_lists_only_fleets_bound_to_the_target_domains(seeded_db):
    _seed_world(seeded_db)
    bench_distribution.register_consumer(
        seeded_db, name="bound-fleet", domains=[A_KEY],
        token_hash=hashlib.sha256(b"a").hexdigest(), created_by="seed",
        kind="fleet", fleet_ref="fleet_a",
    )
    bench_distribution.register_consumer(
        seeded_db, name="other-fleet", domains=[B_KEY],
        token_hash=hashlib.sha256(b"b").hexdigest(), created_by="seed",
        kind="fleet", fleet_ref="fleet_b",
    )
    with _client(seeded_db, _user("lara", _READ_WRITE)) as c:
        page = c.get("/d/dispatch", params={"gap": "ontology"})
    body = _rendered(page.text)
    assert "bound-fleet" in body
    assert "other-fleet" not in body


def test_team_ledger_separates_the_two_origins(seeded_db):
    """值班长要在一份台账里看出谁在跑：来源与外部执行方各占一列。"""
    from src.bench import agent_runs

    _seed_world(seeded_db)
    agent_runs.start(seeded_db, role="agent:warden@aw-key", domain_key=A_KEY)
    agent_runs.record_external_run(
        seeded_db, runner_ref="fleet:fleet_a/post_1#1", role="concept",
        domain_key=A_KEY, outcome="ok", counts={"drafts": 2},
    )
    with _client(seeded_db, _user("lara", _READ_WRITE)) as c:
        page = c.get(f"/d/{A_KEY}/team")
    body = _rendered(page.text)
    assert page.status_code == 200, page.text
    # 表头本身也要在（裸串在引导脚本里也有一份，所以先去掉那份脚本）。
    assert "<th>外部执行方</th>" in body
    assert "<code>fleet:fleet_a/post_1#1</code>" in body


def test_overview_says_who_is_running_per_class(seeded_db):
    from src.bench import agent_runs

    _seed_world(seeded_db)
    agent_runs.start(seeded_db, role="agent:warden@aw-key", domain_key=A_KEY)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as c:
        page = c.get(f"/d/{A_KEY}")
    body = _rendered(page.text)
    assert page.status_code == 200, page.text
    assert "<h2>谁在跑</h2>" in body
    # 内核跑过、舰队没跑过：两类各自给结论，不能合成一句「有活动」。
    assert "<code>agent:warden@aw-key</code>" in body
    assert "还没有跑过" in body


def test_inbox_shows_the_resolved_source_and_marks_legacy(seeded_db):
    world = _seed_world(seeded_db)
    bench_distribution.register_consumer(
        seeded_db, name="ontology-fleet", domains=[A_KEY],
        token_hash=hashlib.sha256(b"t").hexdigest(), created_by="seed",
        kind="fleet", fleet_ref="fleet_a",
    )
    seeded_db.execute(
        "INSERT INTO domain_proposals (domain_id, source, kind, external_key, body, "
        "evidence, evidence_digest, state, submitted_by, sources) VALUES "
        "(%s, 'fleet:fleet_a/post_1', 'company', 'known-1', 'b', '{\"u\":1}'::jsonb, "
        "'d1', 'pending', 'fleet:fleet_a/post_1', '[\"fleet:fleet_a/post_1\"]'::jsonb), "
        "(%s, 'fleet:credential-probe/post_probe', 'company', 'probe-1', 'b', "
        "'{\"u\":2}'::jsonb, 'd2', 'pending', 'probe', "
        "'[\"fleet:credential-probe/post_probe\"]'::jsonb)",
        (world["a"]["id"], world["a"]["id"]),
    )
    seeded_db.commit()

    with _client(seeded_db, _user("lara", _READ_WRITE)) as c:
        page = c.get(f"/d/{A_KEY}/inbox")
    body = _rendered(page.text)
    assert page.status_code == 200, page.text
    # 已登记：显示舰队名 + 岗位，而不是一串原始标识。
    assert "<strong>ontology-fleet</strong>" in body
    assert "<code>post_1</code>" in body
    # 未登记：原样显示并标 legacy——那行没有任何登记能约束它。
    assert "<code>fleet:credential-probe/post_probe</code>" in body
    assert "badge-warn\">legacy</span>" in body


def test_team_shows_open_work_orders_by_kind(seeded_db):
    """团队区与工单页同源展示未完成工单，并按档位分组——混一个总数等于没回答「还在等谁」。"""
    world = _seed_world(seeded_db)
    _task(seeded_db, world["a"], assignee="alice@example.com", target_key="ontology")
    _task(seeded_db, world["a"], assignee="agent:builder@aw-key",
          assignee_kind="kernel-role", assignee_ref="builder", target_key="knowledge")

    with _client(seeded_db, _user("lara", _READ_WRITE)) as c:
        page = c.get(f"/d/{A_KEY}/team")
    body = _rendered(page.text)
    assert page.status_code == 200, page.text
    assert "未完成工单" in body
    assert "内核岗位 1" in body
    assert "人 1" in body
    assert "舰队 0" in body


def test_team_reports_no_open_orders_honestly(seeded_db):
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lara", _READ_WRITE)) as c:
        page = c.get(f"/d/{A_KEY}/team")
    assert "没有未完成的工单" in _rendered(page.text)
