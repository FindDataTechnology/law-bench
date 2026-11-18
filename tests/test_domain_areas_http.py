"""All eight domain areas render over HTTP (§4 integration).

The unit tests pin each store's behaviour; this file pins the thing a user
actually does — open every area of a real domain and get a page. It also states
the two facts the new IA depends on:

- the legacy ``bench`` URL 302s to ``eval-runs`` (no 404, no duplicate page);
- the knowledge and standards areas show *inheritance*: a sub-domain that
  subscribes to the same library as its parent reports the inherited origin, and
  a parent's rubric appears in the child's standards list rather than vanishing.
"""

from __future__ import annotations

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.bench import domain_rubrics, libraries, templates, workspaces
from src.eval import store as eval_store
from src.eval.store import ensure_schema
from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user
from src.web.deps import get_db

SCHEMA = {
    "entity_types": ["clause", "law"],
    "concept_structures": {"clause": ["id"]},
    "relationship_kinds": ["cites_law"],
    "tier_vocabulary": ["gold", "silver", "bronze", "raw"],
    "sensitivity_vocabulary": ["public", "internal", "confidential"],
    "corpus_declaration": {"source_types": ["uploaded"]},
}


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    # rubrics/criteria come from a legacy seed script, not ensure_schema.
    empty_db.execute(
        """
        CREATE TABLE IF NOT EXISTS rubrics (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name TEXT NOT NULL, context TEXT, source TEXT, source_path TEXT,
            description TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now())
        """
    )
    # prompts is another legacy table the bench shelf joins against.
    empty_db.execute(
        """
        CREATE TABLE IF NOT EXISTS prompts (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name TEXT NOT NULL, prompt_type TEXT, content TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now())
        """
    )
    empty_db.execute(
        """
        CREATE TABLE IF NOT EXISTS criteria (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            rubric_id BIGINT NOT NULL REFERENCES rubrics(id) ON DELETE CASCADE,
            name TEXT NOT NULL, description TEXT, guidance TEXT,
            ordinal INTEGER NOT NULL DEFAULT 0)
        """
    )
    empty_db.commit()
    eval_store._ensured_dbs.clear()
    ensure_schema(db_path=empty_db)
    yield empty_db
    # The app caches one shared connection; release it or the per-test DB cannot
    # be dropped ("database is being accessed by other users").
    from src.eval.db import close_shared_conn
    close_shared_conn()


def _world(conn):
    tmpl = templates.create_template(conn, name="areas-tpl", schema=dict(SCHEMA), created_by="t")
    parent = workspaces.instantiate_domain(
        conn, key="areas-parent", name="母域", template_name="areas-tpl",
        template_version=tmpl["version"], created_by="t",
    )
    child = workspaces.instantiate_domain(
        conn, key="areas-child", name="子域", template_name="areas-tpl",
        template_version=tmpl["version"], created_by="t", parent_key="areas-parent",
    )
    for domain, role in ((parent, "lead"), (child, "lead")):
        workspaces.add_member(conn, domain_id=domain["id"], user_id="u1", role=role, added_by="t")
    libraries.create_library(conn, library_key="areas-lib", name="测试库", created_by="t")
    libraries.add_source(conn, library_key="areas-lib", source_key="s1", uri="s3://b/s1", created_by="t")
    libraries.subscribe(conn, domain_id=parent["id"], library_key="areas-lib", created_by="t")
    domain_rubrics.create_for_domain(
        conn, domain_id=parent["id"], name="parent-standard", context="check",
        criteria=[{"name": "c1", "description": "d", "guidance": "g"}],
    )
    return parent, child


def _client(db) -> TestClient:
    app = create_app()
    user = User(sub="u1", name="u1", email="u1@example.com", scopes=["*"], channel="test")

    def _current_user(request: Request) -> User:
        request.state.user = user
        return user

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _current_user
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_idp(monkeypatch):
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)


def test_every_area_renders(conn):
    _world(conn)
    with _client(conn) as c:
        # overview lives at the domain root, the other seven are sub-paths.
        assert c.get("/d/areas-parent").status_code == 200
        for area in (
            "ontology", "knowledge", "eval-standards",
            "eval-runs", "inbox", "publish", "settings",
        ):
            r = c.get(f"/d/areas-parent/{area}")
            assert r.status_code == 200, f"{area} -> {r.status_code}"


def test_legacy_bench_redirects_to_eval_runs(conn):
    _world(conn)
    with _client(conn) as c:
        r = c.get("/d/areas-parent/bench", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].endswith("/d/areas-parent/eval-runs")


def test_estate_and_wizard_render(conn):
    _world(conn)
    with _client(conn) as c:
        estate = c.get("/d")
        wizard = c.get("/d/new?parent=areas-parent")
    assert estate.status_code == 200
    assert "areas-parent" in estate.text and "areas-child" in estate.text
    assert wizard.status_code == 200
    # The wizard previews the parent's inherited vocabulary and sources.
    assert "clause" in wizard.text and "s1" in wizard.text


def test_child_area_shows_inherited_corpus_and_standard(conn):
    _world(conn)
    with _client(conn) as c:
        knowledge = c.get("/d/areas-child/knowledge")
        standards = c.get("/d/areas-child/eval-standards")
    assert knowledge.status_code == 200
    # Inherited, not copied: the library row is attributed to an ancestor.
    assert "areas-lib" in knowledge.text
    assert "areas-parent" in knowledge.text
    assert standards.status_code == 200
    assert "parent-standard" in standards.text


def test_estate_page_computes_the_matrix_once(conn, monkeypatch):
    """The gap chips must not re-run the whole matrix.

    Warm `/d` measured 1465ms with a single domain; about half was a second full
    matrix (a second external count per domain). It was also a second chance for
    the chips and the rows to disagree.
    """
    from src.bench import estate as estate_mod

    _world(conn)
    calls = {"n": 0}
    real = estate_mod.matrix

    def counting(*a, **kw):
        calls["n"] += 1
        return real(*a, **kw)

    monkeypatch.setattr(estate_mod, "matrix", counting)
    with _client(conn) as c:
        r = c.get("/d?gap=knowledge")
    assert r.status_code == 200
    assert calls["n"] == 1, f"matrix ran {calls['n']} times"
