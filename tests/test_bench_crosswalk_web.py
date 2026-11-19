"""Crosswalk read faces (change add-crosswalk-seam, tasks 3.2 and 4.3).

The load-bearing distinction: **relations and crosswalks are two queries, not
one blended list.** A crosswalk is an assertion *about* an entity, never an edge
in the graph. A reader who gets one merged list cannot tell "this entity
participates in these relationships" from "this entity has been mapped outward",
and the ontology-authoring capability explicitly forbids treating a mapping as
a relationship.

The connectivity endpoint mirrors the ERP-side `connector-status.json` shape so
that generator can switch its source without changing its consumers.
"""

from __future__ import annotations

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.bench import store, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema
from src.web.app import create_app
from src.web.auth.deps import User, get_current_user
from src.web.deps import get_db


@pytest.fixture(autouse=True)
def _no_idp(monkeypatch):
    """App startup probes the IdP; tests must not depend on a real Logto.

    Same shim the other web suites use (`test_admin_web._no_idp`): without it the
    suite passes locally (where a stale discovery cache exists) and fails in CI
    with `LogtoUnreachable: Temporary failure in name resolution`.
    """
    from src.web.auth import logto

    monkeypatch.setattr(logto, "verify_reachable", lambda: None)


@pytest.fixture()
def world(empty_db):  # noqa: F811
    # The app opens the process-wide cached connection (get_shared_conn); without
    # closing it the per-test DB cannot be dropped and teardown reports
    # ObjectInUse — a false failure that hides whether the test itself passed.
    from src.eval import db as edb

    edb.close_shared_conn()
    ensure_schema(db_path=empty_db)
    tpl = templates.create_template(
        empty_db, name="erp-tpl",
        schema={
            "entity_types": ["organization", "account"],
            "concept_structures": {},
            "relationship_kinds": ["sells_to"],
            "tier_vocabulary": list(TIERS),
            "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
            "corpus_declaration": {"source_types": []},
        },
        created_by="t",
    )
    dom = workspaces.instantiate_domain(
        empty_db, key="erp", name="ERP", template_name="erp-tpl",
        template_version=tpl["version"], created_by="t",
    )
    workspaces.add_member(empty_db, domain_id=dom["id"], user_id="u1",
                          role="lead", added_by="t")
    store.upsert_knowledge_unit(
        empty_db, kind="organization", namespace="erp",
        external_key="organization:acme", body="Acme",
    )
    store.upsert_knowledge_unit(
        empty_db, kind="crosswalk", namespace="erp", external_key="organization:acme",
        body="mapped",
        attrs={
            "relation": "same_as",
            "peer": {"kind": "external_id", "system": "salesforce", "id": "0014x"},
            "confidence": 0.95,
            "connectivity": {
                "catalog": {"ok": True, "evidence": "cat.json"},
                "executor_tests": {"ok": True, "evidence": "t.ts"},
                # live deliberately missing
            },
        },
    )
    empty_db.commit()
    yield dom
    edb.close_shared_conn()


def _client(db):
    """App with ``get_db`` + ``get_current_user`` overridden (test_admin_web idiom).

    The override sets ``request.state.user`` because the template context
    processor and ``has_scope`` read it — without that, routes that reach the
    chrome misbehave even though the route-level dependency was satisfied.
    """
    app = create_app()

    def _current_user(request: Request) -> User:
        request.state.user = user
        return user

    user = User(
        sub="u1", name="u1", email="u1@example.com",
        scopes=["content:read"], channel="test",
    )
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _current_user
    return TestClient(app)


def test_crosswalk_list_returns_assertions(world, empty_db):
    with _client(empty_db) as c:
        r = c.get("/d/erp/crosswalks")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["crosswalks"]) == 1
    row = body["crosswalks"][0]
    assert row["relation"] == "same_as"
    assert row["peer"]["system"] == "salesforce"
    assert row["confirmed"] is True
    assert row["missing_states"] == ["live"]


def test_crosswalk_list_can_narrow_to_one_entity(world, empty_db):
    with _client(empty_db) as c:
        r = c.get("/d/erp/crosswalks", params={"entity": "organization:acme"})
        empty = c.get("/d/erp/crosswalks", params={"entity": "organization:nope"})
    assert len(r.json()["crosswalks"]) == 1
    assert empty.json()["crosswalks"] == []


def test_connectivity_endpoint_mirrors_the_erp_file_shape(world, empty_db):
    with _client(empty_db) as c:
        r = c.get("/d/erp/crosswalks/connectivity/salesforce")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["connected"] is False
    assert body["missing"] == ["live"]
    for state in ("catalog", "executor_tests", "live"):
        assert set(body["states"][state]) >= {"ok", "evidence"}
    assert body["maps"] == ["organization:acme"]


def test_unknown_system_reports_not_connected_not_404(world, empty_db):
    """An unregistered system is a real answer ("nothing mapped"), not a miss."""
    with _client(empty_db) as c:
        r = c.get("/d/erp/crosswalks/connectivity/kingdee")
    assert r.status_code == 200
    assert r.json()["connected"] is False
    assert r.json()["maps"] == []


def test_relations_and_crosswalks_are_different_shapes(world, empty_db):
    """The two queries must not collapse into one response."""
    from src.bench import quality

    rel = quality.referential_integrity(empty_db, namespace="erp")
    with _client(empty_db) as c:
        cw = c.get("/d/erp/crosswalks").json()
    assert "crosswalks" in cw
    assert "value" in rel and "crosswalks" not in rel, (
        "referential integrity must not carry crosswalk rows"
    )
