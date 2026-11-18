"""Domain archive (§ domain-lifecycle): a domain can leave without data loss.

The point of this capability is that creating a domain stops being a one-way
door. Two things must hold for that: the data survives, and the key is not
handed to a different domain.
"""

from __future__ import annotations

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.bench import authoring, libraries, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema
from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user
from src.web.deps import get_db

SCHEMA = {
    "entity_types": ["clause"], "concept_structures": {"clause": ["id"]},
    "relationship_kinds": ["cites"], "tier_vocabulary": list(TIERS),
    "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
    "corpus_declaration": {"source_types": []},
}


@pytest.fixture()
def conn(empty_db):  # noqa: F811
    ensure_schema(db_path=empty_db)
    templates.create_template(conn=empty_db, name="tpl", schema=dict(SCHEMA), created_by="t")
    for key in ("legal", "trial-x"):
        workspaces.instantiate_domain(
            conn=empty_db, key=key, name=key, template_name="tpl",
            template_version=None, created_by="t",
        )
    empty_db.commit()
    yield empty_db
    from src.eval.db import close_shared_conn
    close_shared_conn()


def test_archive_hides_the_domain_but_keeps_its_data(conn):
    dom = workspaces.get_domain(conn, domain_key="trial-x")
    authoring.authoring_create_unit(conn, domain_key="trial-x", kind="clause",
                                    external_key="c1", body="b", operator="t")
    libraries.create_library(conn, library_key="lib", name="L", created_by="t")
    libraries.add_source(conn, library_key="lib", source_key="s", uri="x", created_by="t")
    libraries.subscribe(conn, domain_id=dom["id"], library_key="lib", created_by="t")
    conn.commit()

    workspaces.archive_domain(conn, domain_key="trial-x", actor="t")

    keys = [d["key"] for d in workspaces.list_domains(conn)]
    assert "trial-x" not in keys and "legal" in keys
    # everything it held is still there
    assert authoring.authoring_get_unit(conn, domain_key="trial-x", kind="clause",
                                       external_key="c1") is not None
    assert libraries.effective_sources(conn, domain_path="trial-x") == {"lib": {"s"}}


def test_archive_is_idempotent_and_keeps_the_first_timestamp(conn):
    first = workspaces.archive_domain(conn, domain_key="trial-x", actor="t")
    second = workspaces.archive_domain(conn, domain_key="trial-x", actor="t")
    assert first["archived_at"] == second["archived_at"]


def test_restore_returns_the_domain_unchanged(conn):
    before = workspaces.get_domain(conn, domain_key="trial-x")
    workspaces.archive_domain(conn, domain_key="trial-x", actor="t")
    after = workspaces.restore_domain(conn, domain_key="trial-x", actor="t")
    assert after["archived_at"] is None
    for field in ("id", "key", "name", "template_id", "template_version", "path"):
        assert after[field] == before[field], field


def test_archived_key_cannot_be_reused(conn):
    workspaces.archive_domain(conn, domain_key="trial-x", actor="t")
    with pytest.raises(ValueError, match="archived"):
        workspaces.instantiate_domain(
            conn=conn, key="trial-x", name="again", template_name="tpl",
            template_version=None, created_by="t",
        )


def test_include_archived_lists_it_again(conn):
    workspaces.archive_domain(conn, domain_key="trial-x", actor="t")
    all_keys = [d["key"] for d in workspaces.list_domains(conn, include_archived=True)]
    assert "trial-x" in all_keys


def test_member_listing_excludes_archived(conn):
    dom = workspaces.get_domain(conn, domain_key="trial-x")
    workspaces.add_member(conn, domain_id=dom["id"], user_id="u1", role="lead", added_by="t")
    conn.commit()
    assert [d["key"] for d in workspaces.list_member_domains(conn, user_id="u1")] == ["trial-x"]
    workspaces.archive_domain(conn, domain_key="trial-x", actor="t")
    assert workspaces.list_member_domains(conn, user_id="u1") == []


def _client(db, *, scopes=("admin",)) -> TestClient:
    app = create_app()
    user = User(sub="u1", name="u1", email="u@e.com", scopes=list(scopes), channel="test")

    def _cu(request: Request) -> User:
        request.state.user = user
        return user

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _cu
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_idp(monkeypatch):
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)


def test_archive_route_is_admin_only(conn):
    with _client(conn, scopes=("content:read",)) as c:
        denied = c.post("/d/trial-x/archive", follow_redirects=False)
    assert denied.status_code in (401, 403)
    assert workspaces.get_domain(conn, domain_key="trial-x")["archived_at"] is None

    with _client(conn) as c:
        ok = c.post("/d/trial-x/archive", follow_redirects=False)
    assert ok.status_code == 303
    assert workspaces.get_domain(conn, domain_key="trial-x")["archived_at"] is not None


def test_restore_route(conn):
    workspaces.archive_domain(conn, domain_key="trial-x", actor="t")
    with _client(conn) as c:
        ok = c.post("/d/trial-x/archive", data={"restore": "1"}, follow_redirects=False)
    assert ok.status_code == 303
    assert workspaces.get_domain(conn, domain_key="trial-x")["archived_at"] is None


def test_admin_page_lists_archived_with_restore(conn):
    workspaces.archive_domain(conn, domain_key="trial-x", actor="t")
    with _client(conn) as c:
        page = c.get("/admin/domains")
    assert page.status_code == 200
    body = page.text
    assert "trial-x" in body
    assert "已归档" in body and "恢复" in body
