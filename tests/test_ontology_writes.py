"""Single-unit writes (§2): entities and relations, all through the kernel.

The kernel already gates the vocabulary and appends events; what these tests pin
is the route layer's own obligations: role gates, resolving relationship
endpoints against *live* entities, and never cascading a delete.
"""

from __future__ import annotations

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.bench import authoring, templates, workspaces
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
    "relationship_kinds": ["cites"],
    "tier_vocabulary": list(TIERS),
    "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
    "corpus_declaration": {"source_types": []},
}


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    templates.create_template(conn=empty_db, name="tpl", schema=dict(SCHEMA), created_by="t")
    dom = workspaces.instantiate_domain(
        conn=empty_db, key="legal", name="法律域", template_name="tpl",
        template_version=None, created_by="t",
    )
    for role, sub in (("expert", "u-expert"), ("lead", "u-lead"), ("annotator", "u-read")):
        workspaces.add_member(conn=empty_db, domain_id=dom["id"], user_id=sub, role=role,
                              added_by="t")
    empty_db.commit()
    yield empty_db
    from src.eval.db import close_shared_conn
    close_shared_conn()


def _client(db, sub: str) -> TestClient:
    app = create_app()
    # Non-admin scopes on purpose: "*" bypasses the domain role gate and would
    # test the platform-admin path instead of the member's.
    user = User(sub=sub, name=sub, email=f"{sub}@e.com",
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


def _events(conn, key=None):
    dom = workspaces.get_domain(conn, domain_key="legal")
    return authoring.authoring_events_for(conn, domain_id=dom["id"], unit_key=key)


def test_expert_creates_an_entity_and_event_is_recorded(conn):
    with _client(conn, "u-expert") as c:
        r = c.post("/d/legal/ontology/units",
                   data={"kind": "clause", "external_key": "gb-50011", "body": "防火规范"},
                   follow_redirects=False)
    assert r.status_code == 303 and "ontology_unit_saved" in r.headers["location"]
    unit = authoring.authoring_get_unit(conn, domain_key="legal", kind="clause",
                                       external_key="gb-50011")
    assert unit["body"] == "防火规范"
    assert [e["op"] for e in _events(conn, "gb-50011")] == ["create"]


def test_kind_outside_the_vocabulary_is_refused_and_nothing_is_written(conn):
    with _client(conn, "u-expert") as c:
        r = c.post("/d/legal/ontology/units",
                   data={"kind": "spaceship", "external_key": "x", "body": "b"},
                   follow_redirects=False)
    assert "ontology_write_failed" in r.headers["location"]
    assert authoring.authoring_list_units(conn, domain_key="legal", include_deleted=True) == []


def test_second_write_updates_instead_of_duplicating(conn):
    with _client(conn, "u-expert") as c:
        c.post("/d/legal/ontology/units",
               data={"kind": "clause", "external_key": "k", "body": "v1"},
               follow_redirects=False)
        r = c.post("/d/legal/ontology/units",
                   data={"kind": "clause", "external_key": "k", "body": "v2"},
                   follow_redirects=False)
    assert "op=updated" in r.headers["location"]
    unit = authoring.authoring_get_unit(conn, domain_key="legal", kind="clause", external_key="k")
    assert unit["body"] == "v2"
    assert [e["op"] for e in _events(conn, "k")] == ["update", "create"]


def test_annotator_cannot_write(conn):
    with _client(conn, "u-read") as c:
        r = c.post("/d/legal/ontology/units",
                   data={"kind": "clause", "external_key": "k", "body": "b"},
                   follow_redirects=False)
    assert r.status_code == 403
    assert authoring.authoring_list_units(conn, domain_key="legal", include_deleted=True) == []


def test_expert_cannot_delete_but_lead_can(conn):
    with _client(conn, "u-expert") as c:
        c.post("/d/legal/ontology/units",
               data={"kind": "clause", "external_key": "k", "body": "b"}, follow_redirects=False)
        denied = c.post("/d/legal/ontology/units/delete",
                        data={"kind": "clause", "external_key": "k"}, follow_redirects=False)
    assert denied.status_code == 403

    with _client(conn, "u-lead") as c:
        ok = c.post("/d/legal/ontology/units/delete",
                    data={"kind": "clause", "external_key": "k"}, follow_redirects=False)
    assert ok.status_code == 303
    unit = authoring.authoring_get_unit(conn, domain_key="legal", kind="clause", external_key="k")
    assert unit["tags"]["deleted"] is True
    assert "delete" in [e["op"] for e in _events(conn, "k")]


def test_relation_requires_live_endpoints(conn):
    with _client(conn, "u-expert") as c:
        c.post("/d/legal/ontology/units", data={"kind": "clause", "external_key": "a", "body": "a"})
        c.post("/d/legal/ontology/units", data={"kind": "clause", "external_key": "b", "body": "b"})
        ok = c.post("/d/legal/ontology/relations",
                    data={"kind": "cites", "from_key": "a", "to_key": "b"},
                    follow_redirects=False)
        bad = c.post("/d/legal/ontology/relations",
                     data={"kind": "cites", "from_key": "a", "to_key": "ghost"},
                     follow_redirects=False)
    assert "ontology_relation_saved" in ok.headers["location"]
    assert "ontology_write_failed" in bad.headers["location"]
    rels = [u for u in authoring.authoring_list_units(conn, domain_key="legal")
            if u["kind"] == "cites"]
    assert len(rels) == 1 and rels[0]["attrs"]["to_key"] == "b"


def test_deleting_an_entity_does_not_cascade_its_relations(conn):
    with _client(conn, "u-lead") as c:
        for k in ("a", "b"):
            c.post("/d/legal/ontology/units", data={"kind": "clause", "external_key": k, "body": k})
        c.post("/d/legal/ontology/relations",
               data={"kind": "cites", "from_key": "a", "to_key": "b"}, follow_redirects=False)
        r = c.post("/d/legal/ontology/units/delete",
                   data={"kind": "clause", "external_key": "b"}, follow_redirects=False)
    assert "related=1" in r.headers["location"]
    rels = [u for u in authoring.authoring_list_units(conn, domain_key="legal")
            if u["kind"] == "cites"]
    assert len(rels) == 1, "cascade would silently widen the blast radius"
    detail = authoring.authoring_unit_detail(conn, domain_key="legal", kind="clause",
                                            external_key="a")
    assert detail["related"][0]["dangling"] is True
