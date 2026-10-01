"""Chrome (topbar) tests for change ``add-web-rbac-and-login-ui``.

Covers Task 5.6: the topbar shows the signed-in identity plus a logout link when
authenticated (a login link when not), and permission-gated actions are hidden
from identities whose scopes cannot use them.

These exercise the ``has_scope`` template helper, which reads
``request.state.user``. A plain dependency override does NOT populate that
attribute, so the client factory below installs an override that sets it
explicitly — letting a test drive the chrome as any identity without minting a
real signed cookie.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.testclient import TestClient

from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user
from src.web.deps import get_db


def _client(seeded_db, monkeypatch, user: User) -> TestClient:
    """A TestClient that resolves every request to ``user`` (state included)."""
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: seeded_db

    async def _dep(request: Request) -> User:
        request.state.user = user
        return user

    app.dependency_overrides[get_current_user] = _dep
    return TestClient(app)


ADMIN = User(
    sub="u-admin", name="管理员", email="admin@example.com",
    scopes=["*"], channel="cookie",
)
EDITOR = User(
    sub="u-editor", name="业务编辑", email="editor@example.com",
    scopes=["content:read", "content:write"], channel="cookie",
)
VIEWER = User(
    sub="u-viewer", name="只读", email="viewer@example.com",
    scopes=["content:read"], channel="cookie",
)
ANON = User(sub="", channel="anonymous")


# --- identity affordance --------------------------------------------------- #


def test_chrome_shows_identity_and_logout_when_authenticated(seeded_db, monkeypatch):
    with _client(seeded_db, monkeypatch, ADMIN) as client:
        body = client.get("/rubrics").text
    assert 'href="/auth/logout"' in body
    assert 'href="/auth/login"' not in body
    assert "管理员" in body


def test_chrome_shows_login_link_when_anonymous(seeded_db, monkeypatch):
    with _client(seeded_db, monkeypatch, ANON) as client:
        body = client.get("/rubrics").text
    assert 'href="/auth/login"' in body
    assert 'href="/auth/logout"' not in body


def test_chrome_nav_visible_for_viewer_hidden_when_anonymous(seeded_db, monkeypatch):
    # /dashboard is a hardcoded nav href (not in the i18n catalog), so it can't
    # collide with the locale JSON embedded in every page.
    with _client(seeded_db, monkeypatch, VIEWER) as client:
        assert 'href="/dashboard"' in client.get("/rubrics").text
    with _client(seeded_db, monkeypatch, ANON) as client:
        assert 'href="/dashboard"' not in client.get("/rubrics").text


# --- permission-gated actions (usability layer; server require_scope rules) - #


def test_chrome_viewer_hides_create_action(seeded_db, monkeypatch):
    with _client(seeded_db, monkeypatch, VIEWER) as client:
        assert "/rubrics/new" not in client.get("/rubrics").text


def test_chrome_editor_sees_create_action(seeded_db, monkeypatch):
    with _client(seeded_db, monkeypatch, EDITOR) as client:
        assert "/rubrics/new" in client.get("/rubrics").text


def test_chrome_rubric_edit_is_editor_but_delete_is_admin(seeded_db, monkeypatch):
    # l_rubric is the local (non-harbor) rubric the seeded DB provides.
    with _client(seeded_db, monkeypatch, EDITOR) as client:
        body = client.get("/rubrics/l_rubric").text
    assert "/rubrics/l_rubric/edit" in body
    assert "/rubrics/l_rubric/delete" not in body

    with _client(seeded_db, monkeypatch, ADMIN) as client:
        assert "/rubrics/l_rubric/delete" in client.get("/rubrics/l_rubric").text


def test_chrome_viewer_sees_no_rubric_actions(seeded_db, monkeypatch):
    with _client(seeded_db, monkeypatch, VIEWER) as client:
        body = client.get("/rubrics/l_rubric").text
    assert "/rubrics/l_rubric/edit" not in body
    assert "/rubrics/l_rubric/delete" not in body
