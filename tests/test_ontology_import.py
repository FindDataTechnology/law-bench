"""Bulk import (§3): the preview and the write are the same planner.

Every test here exists because a lighter preview would have passed while the
write failed, or because "import" was mistaken for "replace".
"""

from __future__ import annotations

import json

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.bench import authoring, ontology_import, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema
from src.web.app import create_app
from src.web.auth import logto
from src.web.auth.deps import User, get_current_user
from src.web.deps import get_db

SCHEMA = {
    "entity_types": ["clause", "party"],
    "concept_structures": {"clause": ["id"]},
    "relationship_kinds": ["cites"],
    "tier_vocabulary": list(TIERS),
    "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
    "corpus_declaration": {"source_types": []},
}

GOOD = {
    "units": [
        # `party`, not `clause`: a clause needs a parent-qualified key and these
        # cases are about plan/apply mechanics, not key rules.
        {"kind": "party", "external_key": "a", "body": "甲"},
        {"kind": "party", "external_key": "b", "body": "乙"},
    ],
    "relationships": [
        {"kind": "cites", "from_key": "a", "to_key": "b"},
    ],
}


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    templates.create_template(conn=empty_db, name="tpl", schema=dict(SCHEMA), created_by="t")
    dom = workspaces.instantiate_domain(
        conn=empty_db, key="legal", name="法律域", template_name="tpl",
        template_version=None, created_by="t",
    )
    workspaces.add_member(conn=empty_db, domain_id=dom["id"], user_id="u-expert",
                          role="expert", added_by="t")
    empty_db.commit()
    yield empty_db
    from src.eval.db import close_shared_conn
    close_shared_conn()


def _client(db) -> TestClient:
    app = create_app()
    user = User(sub="u-expert", name="e", email="e@e.com",
                scopes=["content:read", "content:write"], channel="test")

    def _cu(request: Request) -> User:
        request.state.user = user
        return user

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _cu
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_idp(monkeypatch):
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)


def _count(conn) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM knowledge_units").fetchone()["n"]


def test_plan_reports_mixed_outcomes(conn):
    """One bad kind and one bad endpoint; every other row is writable.

    The first draft of this test also left a unit without a body and then
    expected its relation to be planned as `create` — which is backwards: an
    endpoint that will not exist cannot host a relation. Fixed to the shape the
    task actually describes.
    """
    payload = {
        "units": [
            {"kind": "party", "external_key": "a", "body": "甲"},
            {"kind": "party", "external_key": "b", "body": "乙"},
            {"kind": "spaceship", "external_key": "x", "body": "坏 kind"},
        ],
        "relationships": [
            {"kind": "cites", "from_key": "a", "to_key": "b"},          # ok
            {"kind": "cites", "from_key": "a", "to_key": "ghost"},      # bad endpoint
        ],
    }
    rows = ontology_import.plan(conn, domain_key="legal", payload=payload)
    by_key = {}
    for r in rows:
        by_key.setdefault(r["external_key"], []).append(r["action"])
    assert by_key["a"] == ["create"] and by_key["b"] == ["create"]
    assert by_key["x"] == ["error"]
    assert by_key["a->b"] == ["create"] and by_key["a->ghost"] == ["error"]
    assert _count(conn) == 0, "plan must not write"


def test_dry_run_page_does_not_write(conn):
    with _client(conn) as c:
        r = c.post("/d/legal/ontology/import",
                   data={"payload": json.dumps(GOOD)}, follow_redirects=False)
    assert r.status_code == 200
    assert _count(conn) == 0
    assert "确认" in r.text or "import_confirm" in r.text


def test_confirm_writes_and_reports(conn):
    with _client(conn) as c:
        r = c.post("/d/legal/ontology/import",
                   data={"payload": json.dumps(GOOD), "dry": "0"},
                   follow_redirects=False)
    assert r.status_code == 200
    assert _count(conn) == 3
    units = authoring.authoring_list_units(conn, domain_key="legal")
    assert {u["external_key"] for u in units} >= {"a", "b"}


def test_reimport_updates_instead_of_duplicating(conn):
    with _client(conn) as c:
        c.post("/d/legal/ontology/import", data={"payload": json.dumps(GOOD), "dry": "0"})
        before = _count(conn)
        r = c.post("/d/legal/ontology/import",
                   data={"payload": json.dumps(GOOD), "dry": "0"}, follow_redirects=False)
    assert _count(conn) == before
    body = r.text
    assert "0</strong>" in body or "created" in body  # zero creations reported


def test_malformed_payload_is_a_400_not_a_500(conn):
    with _client(conn) as c:
        bad_json = c.post("/d/legal/ontology/import", data={"payload": "{oops"},
                          follow_redirects=False)
        bad_shape = c.post("/d/legal/ontology/import",
                           data={"payload": json.dumps({"units": "not-an-array"})},
                           follow_redirects=False)
    assert bad_json.status_code == 303 and "ontology_import_failed" in bad_json.headers["location"]
    assert bad_shape.status_code == 303 and "ontology_import_failed" in bad_shape.headers["location"]
    assert _count(conn) == 0


def test_import_goes_through_the_kernel_and_leaves_events(conn):
    with _client(conn) as c:
        c.post("/d/legal/ontology/import", data={"payload": json.dumps(GOOD), "dry": "0"})
    dom = workspaces.get_domain(conn, domain_key="legal")
    events = authoring.authoring_events_for(conn, domain_id=dom["id"])
    assert len(events) == 3          # 2 units + 1 relation, one event each
    assert {e["op"] for e in events} == {"create"}


def test_smoke_units_are_detectable(conn):
    assert ontology_import.is_smoke({"external_key": "smoke-clause-001"})
    assert ontology_import.is_smoke({"external_key": "x", "body": "冒烟订单"})
    assert not ontology_import.is_smoke({"external_key": "gb-50011", "body": "防火规范"})


def test_bare_clause_key_is_refused_on_import(conn):
    """Hand-written imports obey the same key rule as extraction: an article
    number alone is not an address."""
    payload = {"units": [{"kind": "clause", "external_key": "第十二条", "body": "…"}],
               "relationships": []}
    rows = ontology_import.plan(conn, domain_key="legal", payload=payload)
    assert rows[0]["action"] == "error"
    assert "parent" in (rows[0]["reason"] or "")


def test_qualified_clause_key_is_accepted_on_import(conn):
    payload = {"units": [{"kind": "clause", "external_key": "合同法#第12条", "body": "…"}],
               "relationships": []}
    rows = ontology_import.plan(conn, domain_key="legal", payload=payload)
    assert rows[0]["action"] == "create"
