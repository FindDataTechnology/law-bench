"""Web tests for the admin gate (change ``add-ontology-template-and-workspaces``).

Covers OpenSpec tasks 4.3 (权限合成 — two-gate composition, admin bypass,
fail-closed cross-domain denial, permission-aware nav) and 4.4 (跨域隔离 —
non-member denial semantics, no cross-domain data leak), asserting the SCENARIO
semantics of ``specs/web-rbac/spec.md`` and ``specs/domain-workspace/spec.md``.

Two client patterns, per the established suite conventions:

- ``_client(db, user)`` (à la ``test_review_web.py``) — ``create_app()`` with
  ``dependency_overrides`` for ``get_db`` + ``get_current_user``; the override
  also sets ``request.state.user`` so the base-chrome nav (``my_domains`` /
  ``has_scope``) renders from the same identity the route gates saw. Used for
  the two-gate and member-management tests.
- ``cookie_client`` (à la ``test_web_rbac.py``) — the REAL ``get_current_user``
  with a validly-signed session cookie (``session._serializer()``). Used for
  the invitation flow: ``/admin/invite/*`` is auth-exempt and resolves the
  cookie session itself (``admin.py::_session_user``), so only a real signed
  cookie exercises the logged-out vs logged-in accept paths.

Locale: the suite runs with the default ``zh`` catalog, so visible-text
assertions use the zh strings of ``src/web/i18n.py`` (``admin.*`` keys).
Seed data is created inside this module via ``src.bench.templates`` /
``src.bench.workspaces`` — no dependence on the legal-domain registration.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.bench import templates as bench_templates
from src.bench import workspaces
from src.settings import AUTH_COOKIE_NAME
from src.web.app import create_app
from src.web.auth import logto, session
from src.web.auth.deps import User, get_current_user
from src.web.auth.scopes import scopes_from_claims
from src.web.deps import get_db

# A structurally complete template schema (all four vocabularies + the corpus
# declaration); tier/sensitivity sets must equal the kernel's canonical tuples.
VALID_SCHEMA = {
    "entity_types": ["company"],
    "concept_structures": {"indicator": ["name", "unit"]},
    "relationship_kinds": ["belongs_to"],
    "tier_vocabulary": ["gold", "silver", "bronze", "raw"],
    "sensitivity_vocabulary": ["public", "internal", "confidential"],
    "corpus_declaration": {"source_types": []},
}

DOMAIN_A_NAME = "甲域"  # domain the A-side members belong to
DOMAIN_B_NAME = "乙域"  # foreign domain — must never leak to A-only members


# --- seed + client helpers -------------------------------------------------- #


def _seed_world(conn) -> dict:
    """One template, two domains, one lead per domain.

    Domain A (``a-key``) carries the A-side members used by the two-gate tests;
    domain B (``b-key``) exists only so cross-domain denials have real data
    behind them (its lead row proves a 403 hides B's data instead of 404-ing
    an empty domain).
    """
    bench_templates.create_template(
        conn, name="core-template", schema=dict(VALID_SCHEMA), created_by="seed"
    )
    a = workspaces.instantiate_domain(
        conn, key="a-key", name=DOMAIN_A_NAME,
        template_name="core-template", template_version=None, created_by="seed",
    )
    b = workspaces.instantiate_domain(
        conn, key="b-key", name=DOMAIN_B_NAME,
        template_name="core-template", template_version=None, created_by="seed",
    )
    workspaces.add_member(
        conn, domain_id=a["id"], user_id="lead-a", role="lead", added_by="seed"
    )
    workspaces.add_member(
        conn, domain_id=a["id"], user_id="expert-a", role="expert", added_by="seed"
    )
    workspaces.add_member(
        conn, domain_id=b["id"], user_id="lead-b", role="lead", added_by="seed"
    )
    return {"a": a, "b": b}


def _user(sub: str, scopes: list[str], email: str | None = None) -> User:
    """Override-pattern identity; ``_operator_of`` stamps ``user.email``."""
    return User(
        sub=sub, name=sub, email=email or f"{sub}@example.com",
        scopes=list(scopes), channel="test",
    )


def _client(db, user: User) -> TestClient:
    """App with ``get_db`` + ``get_current_user`` overridden to ``user``.

    The override mirrors the real dependency's chrome contract by setting
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


@pytest.fixture
def cookie_client(seeded_db, monkeypatch) -> TestClient:
    """Real auth (no ``get_current_user`` override) against the seeded DB.

    Identity comes from a validly-signed session cookie minted per test via
    :func:`_sign_in` (the ``test_web_rbac.py`` pattern); the IdP startup probe
    is neutralized by the module-wide ``_no_idp`` fixture.
    """
    app = create_app()
    app.dependency_overrides[get_db] = lambda: seeded_db
    with TestClient(app) as client:
        yield client


def _sign_in(client: TestClient, sub: str, scopes: list[str]) -> None:
    """Set a validly-signed session cookie, as ``/auth/callback`` would."""
    normalized = scopes_from_claims({"scope": " ".join(scopes)})
    value = session._serializer().dumps(
        session._normalize({"sub": sub, "name": sub, "scopes": normalized})
    )
    client.cookies.set(AUTH_COOKIE_NAME, value)


def _query_params(response: TestClient.__class__, location: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _active_members(conn, domain_id: int, user_id: str) -> int:
    row = conn.execute(
        "SELECT count(*) AS n FROM domain_members "
        "WHERE domain_id = %s AND user_id = %s AND removed_at IS NULL",
        (domain_id, user_id),
    ).fetchone()
    return row["n"]


# =========================================================================== #
# Task 4.3 — 权限合成 (web-rbac delta: 双道执法 / 管理员直通 / fail-closed)      #
# =========================================================================== #


# --- 双道执法: gate 1 (platform scope) -------------------------------------- #


def test_member_without_content_read_is_403_missing_scope(seeded_db):
    """域角色过但平台 scope 拒: lead of A without content:read -> 403 missing scope.

    The scope gate is checked first, so even a legitimate domain lead cannot
    reach the domain page without the platform scope (require_scope fires).
    """
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lead-a", ["content:write"])) as c:
        r = c.get("/admin/domains/a-key")
    assert r.status_code == 403
    assert r.json()["detail"] == "missing scope: content:read"


def test_scope_gate_runs_before_domain_gate(seeded_db):
    """双道顺序: non-member with NO scope sees 'missing scope', not 无该域权限.

    A user failing BOTH gates gets the scope denial — proving require_scope
    composes before require_domain_role on the route dependency list.
    """
    _seed_world(seeded_db)
    with _client(seeded_db, _user("nobody", [])) as c:
        r = c.get("/admin/domains/b-key")
    assert r.status_code == 403
    assert r.json()["detail"] == "missing scope: content:read"


# --- 双道执法: gate 2 (domain role) ----------------------------------------- #


def test_content_write_without_membership_is_403_no_domain_permission(seeded_db):
    """平台 scope 过但域角色拒: content:write holder with no membership -> 403.

    web-rbac scenario 「平台 scope 不足以越过域检查」: platform scope alone
    never opens a domain the user holds no membership in.
    """
    _seed_world(seeded_db)
    with _client(seeded_db, _user("writer", ["content:read", "content:write"])) as c:
        r = c.get("/admin/domains/b-key")
    assert r.status_code == 403
    assert r.json()["detail"] == "无该域权限"
    # 非成员跨域读取被拒: B's data (its name, its lead) appears nowhere.
    assert DOMAIN_B_NAME not in r.text
    assert "lead-b" not in r.text


def test_expert_rank_below_required_lead_is_403(seeded_db):
    """角色序 fail-closed: an expert member is below the required lead rank."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("expert-a", ["content:read", "content:write"])) as c:
        r = c.get("/admin/domains/a-key")
    assert r.status_code == 403
    assert r.json()["detail"] == "无该域权限"


def test_member_of_a_only_is_403_not_404_on_domain_b(seeded_db):
    """fail-closed 跨域: member ONLY of A requests domain B -> 403, never 404.

    The spec forbids disguising a cross-domain denial as a 404 (that would
    leak domain existence); the honest 「无该域权限」 is the required answer.
    """
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lead-a", ["content:read", "content:write"])) as c:
        r = c.get("/admin/domains/b-key")
    assert r.status_code == 403  # the permission denial, NOT a disguised 404
    assert r.json()["detail"] == "无该域权限"


def test_unknown_domain_key_is_403_not_404(seeded_db):
    """fail-closed: an unknown domain key is also 「无该域权限」, not 404."""
    with _client(seeded_db, _user("writer", ["content:read", "content:write"])) as c:
        r = c.get("/admin/domains/no-such-domain")
    assert r.status_code == 403
    assert r.json()["detail"] == "无该域权限"


# --- 管理员直通 -------------------------------------------------------------- #


def test_admin_scope_bypasses_domain_check(seeded_db):
    """管理员跨域全权: scopes=['*'] opens any domain with zero membership."""
    world = _seed_world(seeded_db)
    with _client(seeded_db, _user("admin-u", ["*"])) as c:
        r = c.get(f"/admin/domains/{world['b']['key']}")
    assert r.status_code == 200
    assert DOMAIN_B_NAME in r.text
    assert "lead-b" in r.text  # admin sees the full member table


def test_admin_scope_passes_admin_templates(seeded_db):
    """Platform-admin gate: '*' passes /admin/templates (and renders its page)."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("admin-u", ["*"])) as c:
        r = c.get("/admin/templates")
    assert r.status_code == 200
    assert "core-template" in r.text


def test_non_admin_is_403_on_admin_templates(seeded_db):
    """Template management is platform-admin exclusive — a writer is 403."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("writer", ["content:read", "content:write"])) as c:
        r = c.get("/admin/templates")
    assert r.status_code == 403
    assert r.json()["detail"] == "missing scope: admin"


def test_admin_create_domain_via_form(seeded_db):
    """Admin instantiates a domain through the list-page form (flash redirect)."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("admin-u", ["*"])) as c:
        r = c.post(
            "/admin/domains",
            data={"key": "c-key", "name": "丙域", "template_name": "core-template",
                  "template_version": ""},
            follow_redirects=False,
        )
    assert r.status_code == 303
    assert "msg=flash.domain_created" in r.headers["location"]
    created = workspaces.get_domain(seeded_db, domain_key="c-key")
    assert created is not None and created["name"] == "丙域"
    assert created["created_by"] == "admin-u@example.com"


# --- 导航按域过滤 (web-rbac delta) ------------------------------------------ #


def test_nav_shows_only_member_domain_and_no_admin_gate(seeded_db):
    """导航按域过滤 (C5 域优先): an A-only member sees the single 「我的域」 door
    (→ /d) and never another domain, and never the admin gate.

    The chrome deliberately does not enumerate domains any more: the domain list
    IS the /d page, and repeating per-domain links in the top bar is the
    conflation this change removes. (Label strings live in the
    ``window.__LOCALE__`` bootstrap on every page, so the assertions target
    rendered nav elements — hrefs — not bare text.)
    """
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lead-a", ["content:read", "content:write"])) as c:
        r = c.get("/rubrics")
    assert r.status_code == 200
    assert '>我的域</a>' in r.text                    # the one door renders...
    assert 'href="/d"' in r.text                      # ...pointing at the domain list
    assert '/admin/domains/' not in r.text            # no per-domain nav links
    assert DOMAIN_B_NAME not in r.text and "b-key" not in r.text
    assert '/admin/templates"' not in r.text         # no admin gate link
    assert '/admin/domains"' not in r.text           # no all-domains list link


def test_admin_nav_shows_gate_and_no_domain_entries(seeded_db):
    """Admin ('*' scope, no memberships) sees 管理门 and zero 我的域 entries."""
    _seed_world(seeded_db)
    with _client(seeded_db, _user("admin-u", ["*"])) as c:
        r = c.get("/admin/templates")
    assert r.status_code == 200
    assert 'class="muted">管理门' in r.text
    assert '/admin/templates"' in r.text
    assert '/admin/domains"' in r.text
    assert 'class="muted">我的域' not in r.text      # no memberships -> no section
    assert DOMAIN_A_NAME not in r.text and DOMAIN_B_NAME not in r.text


def test_anonymous_invite_page_renders_without_my_domains(cookie_client, seeded_db):
    """Anonymous chrome: the invite page renders, with no 我的域 entries."""
    world = _seed_world(seeded_db)
    token = "anon-nav-check-token"
    workspaces.create_invitation(
        seeded_db,
        domain_id=world["a"]["id"], role="expert", invited_by="seed",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        token_hash=_digest(token),
    )
    r = cookie_client.get(f"/admin/invite/{token}")  # auth-exempt path
    assert r.status_code == 200
    assert 'class="muted">我的域' not in r.text
    assert DOMAIN_A_NAME in r.text  # the invite itself shows its domain


# =========================================================================== #
# 邀请全流程 (domain-workspace delta: 邀请制成员准入)                           #
# =========================================================================== #


def _mint_invitation(conn, client, domain_key: str, role: str, days: str = "7") -> str:
    """Create an invitation through the lead form; return the plaintext token.

    The plaintext link exists exactly once — in the creation flash redirect —
    so this helper doubles as the one-time-disclosure assertion.
    """
    r = client.post(
        f"/admin/domains/{domain_key}/invitations",
        data={"role": role, "expires_days": days},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    params = _query_params(type("R", (), {}), r.headers["location"])
    assert params["msg"] == "flash.invitation_created"
    link = params["detail"]
    assert link.startswith("/admin/invite/")
    token = link.rsplit("/", 1)[1]
    assert r.headers["location"].count(token) == 1  # shown exactly once
    return token


def test_invitation_plaintext_shown_once_and_only_hash_stored(seeded_db):
    """The plaintext token rides the flash once; the DB stores only sha256."""
    world = _seed_world(seeded_db)
    with _client(seeded_db, _user("lead-a", ["content:read", "content:write"])) as c:
        token = _mint_invitation(seeded_db, c, "a-key", "expert")
        # The domain page (the flash target) shows the hash prefix only —
        # the plaintext is never re-displayed.
        page = c.get("/admin/domains/a-key")
    assert page.status_code == 200
    assert token not in page.text
    assert _digest(token)[:12] in page.text

    row = seeded_db.execute(
        "SELECT token_hash FROM domain_invitations WHERE domain_id = %s",
        (world["a"]["id"],),
    ).fetchone()
    assert row["token_hash"] == _digest(token)
    assert row["token_hash"] != token  # plaintext never persisted
    assert workspaces.get_invitation(seeded_db, token_hash=token) is None


def test_invite_view_anonymous_shows_domain_and_role(cookie_client, seeded_db):
    """Anonymous GET of the invite link: 200 with domain/role info, no login."""
    world = _seed_world(seeded_db)
    token = "viewable-token"
    workspaces.create_invitation(
        seeded_db, domain_id=world["a"]["id"], role="expert", invited_by="lead-a@example.com",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        token_hash=_digest(token),
    )
    r = cookie_client.get(f"/admin/invite/{token}")
    assert r.status_code == 200
    assert DOMAIN_A_NAME in r.text and "a-key" in r.text
    assert "专家" in r.text          # zh role label for expert
    assert "lead-a@example.com" in r.text
    assert "登录后接受" in r.text     # not signed in -> login-first affordance


def test_accept_logged_out_redirects_into_login_flow(cookie_client, seeded_db):
    """POST accept without a session redirects to /auth/login with next=... .

    The admin.py contract: the login round-trip returns to the invite view
    (``next=/admin/invite/{token}``) where the now-signed-in invitee accepts.
    """
    world = _seed_world(seeded_db)
    token = "logged-out-token"
    workspaces.create_invitation(
        seeded_db, domain_id=world["a"]["id"], role="expert", invited_by="seed",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        token_hash=_digest(token),
    )
    r = cookie_client.post(f"/admin/invite/{token}/accept", follow_redirects=False)
    assert r.status_code == 302
    location = r.headers["location"]
    assert location.startswith("/auth/login?next=")
    assert f"/admin/invite/{token}" in location  # comes back to the invite page
    # No membership was created for an anonymous identity.
    assert _active_members(seeded_db, world["a"]["id"], "") == 0


def test_accept_logged_in_joins_domain_and_invalidates_token(cookie_client, seeded_db):
    """邀请-接受全流程: signed-in accept -> membership + token dead."""
    world = _seed_world(seeded_db)
    with _client(seeded_db, _user("lead-a", ["content:read", "content:write"])) as lead:
        token = _mint_invitation(seeded_db, lead, "a-key", "expert")

    _sign_in(cookie_client, "invitee", ["content:read", "content:write"])
    # The view resolves the cookie session itself and offers the accept form.
    view = cookie_client.get(f"/admin/invite/{token}")
    assert view.status_code == 200
    assert "接受邀请入域" in view.text
    assert "invitee" in view.text  # 当前身份

    r = cookie_client.post(f"/admin/invite/{token}/accept", follow_redirects=False)
    assert r.status_code == 303
    params = _query_params(type("R", (), {}), r.headers["location"])
    assert params["msg"] == "flash.invite_accepted"

    # Membership created with the INVITED role...
    assert workspaces.get_active_role(
        seeded_db, domain_id=world["a"]["id"], user_id="invitee"
    ) == "expert"
    # ...and the invitation is marked accepted.
    invitation = workspaces.get_invitation(seeded_db, token_hash=_digest(token))
    assert invitation["accepted_at"] is not None
    assert invitation["accepted_by"] == "invitee"

    # The invite view now shows the neutral invalid (used) state.
    after = cookie_client.get(f"/admin/invite/{token}")
    assert after.status_code == 200
    assert "邀请无效" in after.text


def test_invitation_cannot_be_reused(cookie_client, seeded_db):
    """已用令牌拒绝: a second accept fails and creates no second membership."""
    world = _seed_world(seeded_db)
    with _client(seeded_db, _user("lead-a", ["content:read", "content:write"])) as lead:
        token = _mint_invitation(seeded_db, lead, "a-key", "expert")
    _sign_in(cookie_client, "first-user", ["content:read"])
    assert cookie_client.post(
        f"/admin/invite/{token}/accept", follow_redirects=True
    ).status_code == 200

    # A different identity tries the same (already-consumed) token.
    _sign_in(cookie_client, "second-user", ["content:read"])
    r = cookie_client.post(f"/admin/invite/{token}/accept", follow_redirects=False)
    assert r.status_code == 303  # InvitationError path -> flash, never a 500
    params = _query_params(type("R", (), {}), r.headers["location"])
    assert params["msg"] == "flash.invite_failed" and params["err"] == "1"
    assert "already accepted" in params["detail"]

    # Exactly one membership (the first accepter's); none for second-user.
    assert _active_members(seeded_db, world["a"]["id"], "first-user") == 1
    assert _active_members(seeded_db, world["a"]["id"], "second-user") == 0


def test_expired_invitation_is_rejected_with_no_membership(cookie_client, seeded_db):
    """过期令牌拒绝: expiry error surfaced, binding refused, no member row."""
    world = _seed_world(seeded_db)
    token = "expired-token"
    workspaces.create_invitation(
        seeded_db, domain_id=world["b"]["id"], role="annotator", invited_by="seed",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        token_hash=_digest(token),
    )
    # The view renders the neutral invalid state for an expired token.
    view = cookie_client.get(f"/admin/invite/{token}")
    assert view.status_code == 200
    assert "邀请无效" in view.text

    _sign_in(cookie_client, "late-invitee", ["content:read"])
    r = cookie_client.post(f"/admin/invite/{token}/accept", follow_redirects=False)
    assert r.status_code == 303
    params = _query_params(type("R", (), {}), r.headers["location"])
    assert params["msg"] == "flash.invite_failed" and params["err"] == "1"
    assert "expired" in params["detail"]  # the message names the expiry
    assert _active_members(seeded_db, world["b"]["id"], "late-invitee") == 0


def test_unknown_or_tampered_token_never_500s(cookie_client, seeded_db):
    """Unknown/tampered token: view + accept both fail closed, never a 500."""
    world = _seed_world(seeded_db)
    _sign_in(cookie_client, "attacker", ["content:read"])

    view = cookie_client.get("/admin/invite/not-a-real-token")
    assert view.status_code == 200
    assert "邀请无效" in view.text

    r = cookie_client.post(
        "/admin/invite/tampered-token/accept", follow_redirects=False
    )
    assert r.status_code == 303  # error flash, not an exception
    params = _query_params(type("R", (), {}), r.headers["location"])
    assert params["msg"] == "flash.invite_failed" and params["err"] == "1"
    assert _active_members(seeded_db, world["a"]["id"], "attacker") == 0
    assert _active_members(seeded_db, world["b"]["id"], "attacker") == 0


# =========================================================================== #
# 成员管理 via HTTP (lead flow + 留痕)                                          #
# =========================================================================== #


_LEAD_A = ("lead-a", ["content:read", "content:write"])


def test_lead_adds_member_via_form(seeded_db):
    """Lead POSTs the add form -> active membership row with operator stamp."""
    world = _seed_world(seeded_db)
    with _client(seeded_db, _user(*_LEAD_A)) as c:
        r = c.post(
            "/admin/domains/a-key/members/add",
            data={"user_id": "new-member", "role": "expert"},
            follow_redirects=False,
        )
    assert r.status_code == 303
    params = _query_params(type("R", (), {}), r.headers["location"])
    assert params["msg"] == "flash.member_added" and params["name"] == "new-member"

    members = workspaces.list_members(seeded_db, domain_id=world["a"]["id"])
    added = [m for m in members if m["user_id"] == "new-member"]
    assert len(added) == 1 and added[0]["role"] == "expert"
    assert added[0]["added_by"] == "lead-a@example.com"  # operator stamped


def test_lead_changes_role_append_only_with_audit(seeded_db):
    """角色变更留痕: old row retired (kept), new row active with operator."""
    world = _seed_world(seeded_db)
    workspaces.add_member(
        seeded_db, domain_id=world["a"]["id"], user_id="member-x",
        role="expert", added_by="seed",
    )
    with _client(seeded_db, _user(*_LEAD_A)) as c:
        r = c.post(
            "/admin/domains/a-key/members/role",
            data={"user_id": "member-x", "role": "annotator"},
            follow_redirects=False,
        )
    assert r.status_code == 303
    params = _query_params(type("R", (), {}), r.headers["location"])
    assert params["msg"] == "flash.member_role_changed"

    # Enforcement follows the NEW role; history keeps the OLD one.
    assert workspaces.get_active_role(
        seeded_db, domain_id=world["a"]["id"], user_id="member-x"
    ) == "annotator"
    rows = seeded_db.execute(
        "SELECT role, added_by, removed_at FROM domain_members "
        "WHERE domain_id = %s AND user_id = %s ORDER BY id",
        (world["a"]["id"], "member-x"),
    ).fetchall()
    assert [(row["role"], row["added_by"], row["removed_at"] is None) for row in rows] == [
        ("expert", "seed", False),          # retired history row, intact
        ("annotator", "lead-a@example.com", True),  # active row, operator stamped
    ]


def test_lead_removes_member_immediate_access_loss(seeded_db):
    """移除即时生效: removed member loses access; history row is retained."""
    world = _seed_world(seeded_db)
    workspaces.add_member(
        seeded_db, domain_id=world["a"]["id"], user_id="gone-soon",
        role="expert", added_by="seed",
    )
    with _client(seeded_db, _user(*_LEAD_A)) as c:
        r = c.post(
            "/admin/domains/a-key/members/remove",
            data={"user_id": "gone-soon"},
            follow_redirects=False,
        )
    assert r.status_code == 303
    params = _query_params(type("R", (), {}), r.headers["location"])
    assert params["msg"] == "flash.member_removed"

    assert workspaces.get_active_role(
        seeded_db, domain_id=world["a"]["id"], user_id="gone-soon"
    ) is None
    assert all(
        m["user_id"] != "gone-soon"
        for m in workspaces.list_members(seeded_db, domain_id=world["a"]["id"])
    )
    row = seeded_db.execute(
        "SELECT removed_at FROM domain_members "
        "WHERE domain_id = %s AND user_id = %s",
        (world["a"]["id"], "gone-soon"),
    ).fetchone()
    assert row["removed_at"] is not None  # history preserved, only retired


def test_lead_of_domain_a_cannot_post_member_add_on_domain_b(seeded_db):
    """跨域成员操作被拒 (SPEC): A-lead POSTs B's member add -> 403 无该域权限.

    web-rbac 「平台 scope 不足以越过域检查」 + domain-workspace 「非成员跨域
    读取被拒」: the write route must be two-gated like the GET detail page.

    BUG REPRO (currently RED against src/): this returns 303 flash.member_added
    and actually inserts "intruder" as a lead of domain B — the four write
    routes in src/web/routes/admin.py (members/add|role|remove, invitations)
    declare only ``require_scope("content:write")`` and no
    ``require_domain_role``, contradicting design D5 (「/admin/* 全部要求
    admin 平台 scope + 对应域角色合成」) and the module's own docstrings.
    Fix: add ``Depends(require_domain_role("lead"))`` to those routes.
    """
    world = _seed_world(seeded_db)
    with _client(seeded_db, _user(*_LEAD_A)) as c:
        r = c.post(
            "/admin/domains/b-key/members/add",
            data={"user_id": "intruder", "role": "lead"},
            follow_redirects=False,
        )
    assert r.status_code == 403, (
        f"expected the domain-role gate, got {r.status_code} "
        f"-> {r.headers.get('location')}"
    )
    assert r.json()["detail"] == "无该域权限"
    assert _active_members(seeded_db, world["b"]["id"], "intruder") == 0


def test_lead_of_domain_a_cannot_create_invitation_on_domain_b(seeded_db):
    """跨域邀请被拒 (SPEC): A-lead cannot mint invitations for domain B.

    BUG REPRO (currently RED, same missing gate as the member-add repro):
    the POST succeeds and mints a usable one-time invitation for domain B.
    """
    world = _seed_world(seeded_db)
    with _client(seeded_db, _user(*_LEAD_A)) as c:
        r = c.post(
            "/admin/domains/b-key/invitations",
            data={"role": "lead", "expires_days": "7"},
            follow_redirects=False,
        )
    assert r.status_code == 403, (
        f"expected the domain-role gate, got {r.status_code} "
        f"-> {r.headers.get('location')}"
    )
    assert r.json()["detail"] == "无该域权限"
    rows = seeded_db.execute(
        "SELECT count(*) AS n FROM domain_invitations WHERE domain_id = %s",
        (world["b"]["id"],),
    ).fetchone()
    assert rows["n"] == 0


def test_admin_can_manage_members_across_domains(seeded_db):
    """管理员跨域全权: '*' adds a member in any domain (bypasses role check)."""
    world = _seed_world(seeded_db)
    with _client(seeded_db, _user("admin-u", ["*"])) as c:
        r = c.post(
            "/admin/domains/b-key/members/add",
            data={"user_id": "admin-appointee", "role": "expert"},
            follow_redirects=False,
        )
    assert r.status_code == 303
    assert _active_members(seeded_db, world["b"]["id"], "admin-appointee") == 1


# =========================================================================== #
# Task 4.4 — 跨域隔离 (content-level: B 的数据零泄漏给 A-only 成员)             #
# =========================================================================== #


def test_domain_b_data_never_leaks_to_a_only_member(seeded_db):
    """域间内容不可见: every 200 reachable by an A-only member is B-free.

    A-only member sweeps the pages they can reach; the /admin surface that
    would show B 403s (JSON denial with no data), and their own domain page
    carries only A's records.
    """
    _seed_world(seeded_db)
    with _client(seeded_db, _user("lead-a", ["content:read", "content:write"])) as c:
        own = c.get("/admin/domains/a-key")
        others = c.get("/admin/domains/b-key")
        listing = c.get("/admin/domains")     # admin-scope page -> 403
        chrome = c.get("/rubrics")
    assert own.status_code == 200
    assert DOMAIN_A_NAME in own.text and "expert-a" in own.text
    assert DOMAIN_B_NAME not in own.text and "lead-b" not in own.text and "b-key" not in own.text

    assert others.status_code == 403
    assert others.json()["detail"] == "无该域权限"
    assert DOMAIN_B_NAME not in others.text and "lead-b" not in others.text

    assert listing.status_code == 403  # non-admin: nothing about any domain leaks
    assert DOMAIN_B_NAME not in listing.text and DOMAIN_A_NAME not in listing.text

    assert chrome.status_code == 200
    assert DOMAIN_B_NAME not in chrome.text and "b-key" not in chrome.text
    # The chrome carries the domain DOOR, not a domain enumeration (C5): the
    # only way A appears in the top bar is through /d, one click away.
    assert '>我的域</a>' in chrome.text and 'href="/d"' in chrome.text
    assert DOMAIN_A_NAME not in chrome.text
