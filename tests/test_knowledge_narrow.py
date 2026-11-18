"""A domain lead may narrow its own corpus — subtraction only (§4.3).

The rule "a sub-domain may narrow, never widen" already existed in the resolver.
What did not exist was a way for the person who owns the sub-domain to exercise
it without asking a platform admin. These tests pin the three ways that could go
wrong:

- a lead **widening** past the parent must fail at submit time with a message
  naming the ungranted source (not a success flash and a broken scope later);
- a non-lead (expert/annotator) must not reach the write at all;
- a root domain may narrow to any subset of its own library's sources.
"""

from __future__ import annotations

import re

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.bench import libraries, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema
from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user
from src.web.deps import get_db

SCHEMA = {
    "entity_types": ["clause"],
    "concept_structures": {"clause": ["id"]},
    "relationship_kinds": ["cites_law"],
    "tier_vocabulary": list(TIERS),
    "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
    "corpus_declaration": {"source_types": []},
}


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    yield empty_db
    from src.eval.db import close_shared_conn
    close_shared_conn()


def _world(conn, *, member_role: str = "lead"):
    templates.create_template(conn, name="tpl", schema=dict(SCHEMA), created_by="t")
    parent = workspaces.instantiate_domain(
        conn, key="legal", name="法律域", template_name="tpl",
        template_version=None, created_by="t",
    )
    child = workspaces.instantiate_domain(
        conn, key="cr", name="合同审查", template_name="tpl",
        template_version=None, created_by="t", parent_key="legal",
    )
    workspaces.add_member(conn, domain_id=child["id"], user_id="u1", role=member_role,
                          added_by="t")
    libraries.create_library(conn, library_key="law", name="法规库", created_by="t")
    for s in ("statutes", "judicial", "local"):
        libraries.add_source(conn, library_key="law", source_key=s, uri=f"s3://b/{s}",
                             created_by="t")
    # The parent grants two of the three; `local` is never granted.
    libraries.subscribe(conn, domain_id=parent["id"], library_key="law", created_by="t",
                        source_filter=["statutes", "judicial"])
    conn.commit()
    return parent, child


def _client(db, *, scopes=("*",)) -> TestClient:
    app = create_app()
    user = User(sub="u1", name="u1", email="u1@example.com", scopes=list(scopes),
                channel="test")

    def _cu(request: Request) -> User:
        request.state.user = user
        return user

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _cu
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_idp(monkeypatch):
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)


def test_child_narrows_to_a_subset(conn):
    _world(conn)
    with _client(conn) as c:
        r = c.post("/d/cr/knowledge/narrow",
                   data={"library_key": "law", "source": ["statutes"]},
                   follow_redirects=False)
    assert r.status_code == 303
    assert "narrowed" in r.headers["location"]
    scope = libraries.effective_sources(conn, domain_path="legal/cr")
    assert scope == {"law": {"statutes"}}


def test_child_cannot_widen_past_the_parent(conn):
    _world(conn)
    with _client(conn) as c:
        r = c.post("/d/cr/knowledge/narrow",
                   data={"library_key": "law", "source": ["statutes", "local"]},
                   follow_redirects=False)
    assert r.status_code == 303
    assert "narrow_failed" in r.headers["location"]
    # Nothing was written: the child still inherits the parent's two sources.
    scope = libraries.effective_sources(conn, domain_path="legal/cr")
    assert scope == {"law": {"statutes", "judicial"}}


def test_empty_selection_is_refused(conn):
    _world(conn)
    with _client(conn) as c:
        r = c.post("/d/cr/knowledge/narrow", data={"library_key": "law"},
                   follow_redirects=False)
    assert "narrow_failed" in r.headers["location"]


def test_expert_cannot_change_the_scope(conn):
    # Not a platform admin: with scopes=["*"] the role gate is bypassed by
    # design, which would make this test assert the wrong thing.
    _world(conn, member_role="expert")
    with _client(conn, scopes=("content:read", "content:write")) as c:
        r = c.post("/d/cr/knowledge/narrow",
                   data={"library_key": "law", "source": ["statutes"]},
                   follow_redirects=False)
    assert r.status_code in (401, 403)
    scope = libraries.effective_sources(conn, domain_path="legal/cr")
    assert scope == {"law": {"statutes", "judicial"}}   # unchanged


def test_root_may_narrow_its_own_grant(conn):
    parent, _child = _world(conn)
    workspaces.add_member(conn, domain_id=parent["id"], user_id="u1", role="lead", added_by="t")
    conn.commit()
    with _client(conn) as c:
        r = c.post("/d/legal/knowledge/narrow",
                   data={"library_key": "law", "source": ["judicial"]},
                   follow_redirects=False)
    assert "narrowed" in r.headers["location"]
    assert libraries.effective_sources(conn, domain_path="legal") == {"law": {"judicial"}}


def test_unknown_source_is_refused(conn):
    _world(conn)
    with _client(conn) as c:
        r = c.post("/d/cr/knowledge/narrow",
                   data={"library_key": "law", "source": ["ghost"]},
                   follow_redirects=False)
    assert "narrow_failed" in r.headers["location"]


def _rendered(html: str) -> str:
    """The body only — the whole i18n catalogue is inlined in a <script>, so a
    plain substring test on ``response.text`` finds labels that were never
    rendered (this has fooled me twice now)."""
    i = html.find("<body")
    body = html[i:] if i >= 0 else html
    return re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.S)


def test_form_is_shown_to_a_lead_only(conn):
    _world(conn, member_role="lead")
    with _client(conn, scopes=("content:read", "content:write")) as c:
        lead_page = c.get("/d/cr/knowledge")
    assert lead_page.status_code == 200
    assert "收窄本域取材范围" in _rendered(lead_page.text)

    _world2(conn)
    with _client(conn, scopes=("content:read", "content:write")) as c:
        expert_page = c.get("/d/cr2/knowledge")
    assert expert_page.status_code == 200
    assert "收窄本域取材范围" not in _rendered(expert_page.text)


def _world2(conn):
    """Second world in the same DB: a sibling child whose member is an expert."""
    parent = workspaces.get_domain(conn, domain_key="legal")
    other = workspaces.instantiate_domain(
        conn, key="cr2", name="合同审查2", template_name="tpl",
        template_version=None, created_by="t", parent_key="legal",
    )
    workspaces.add_member(conn, domain_id=other["id"], user_id="u1", role="expert",
                          added_by="t")
    libraries.subscribe(conn, domain_id=parent["id"], library_key="law", created_by="t",
                        source_filter=["statutes", "judicial"])
    conn.commit()
