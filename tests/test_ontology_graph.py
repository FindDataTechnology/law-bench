"""The ontology graph and the grounding column (§4/5.3 of the concept layer).

The graph exists to answer two questions a list cannot: *what rests on what*, and
*what rests on nothing*. The second is the one that matters — an ungrounded
concept is the gap this whole line of work is about, so it is drawn out of the
canvas and listed explicitly rather than left floating.
"""

from __future__ import annotations

import re

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

import packs.legal  # noqa: F401 — registers fold rules and the category predicate
from src.bench import authoring, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema
from src.web.routes.console import _ontology_graph, _grounding_map

SCHEMA = {
    "entity_types": ["clause", "law", "concept"],
    "concept_structures": {"clause": ["id"], "concept": ["definition"]},
    "relationship_kinds": ["cites_law", "defines"],
    "tier_vocabulary": list(TIERS),
    "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
    "corpus_declaration": {"source_types": []},
}


def _unit(kind, key, attrs=None):
    return {"kind": kind, "external_key": key, "body": key, "tier": "raw",
            "tags": {}, "attrs": attrs or {}}


def test_graph_splits_concepts_from_documents_and_keeps_edges():
    units = [
        _unit("concept", "违约 责任".replace(" ", "")),
        _unit("law", "合同法"),
        _unit("defines", "x", {"from_key": "违约责任", "to_key": "合同法"}),
    ]
    g = _ontology_graph(units)
    assert [u["external_key"] for u in g["concepts"]] == ["违约责任"]
    assert [u["external_key"] for u in g["documents"]] == ["合同法"]
    assert g["edges"] == [{"from": "违约责任", "to": "合同法", "kind": "defines"}]
    assert g["isolated"] == []


def test_ungrounded_units_are_named_not_hidden():
    units = [
        _unit("concept", "违约责任"),
        _unit("concept", "举证责任"),          # nothing rests on it
        _unit("law", "合同法"),
        _unit("defines", "x", {"from_key": "违约责任", "to_key": "合同法"}),
    ]
    g = _ontology_graph(units)
    assert [u["external_key"] for u in g["isolated"]] == ["举证责任"]


def test_deleted_units_stay_out_of_the_picture():
    gone = _unit("concept", "已删概念")
    gone["tags"] = {"deleted": True}
    g = _ontology_graph([_unit("concept", "留下的"), gone])
    assert [u["external_key"] for u in g["concepts"]] == ["留下的"]


def test_ordering_is_deterministic():
    """A picture that reshuffles on reload is not readable as a structure."""
    units = [_unit("concept", k) for k in ("丙", "甲", "乙")]
    first = [u["external_key"] for u in _ontology_graph(units)["concepts"]]
    second = [u["external_key"] for u in _ontology_graph(list(reversed(units)))["concepts"]]
    assert first == second == sorted(["甲", "乙", "丙"])


def test_truncation_is_reported():
    units = [_unit("concept", f"概念{i:02d}") for i in range(8)]
    g = _ontology_graph(units, limit=5)
    assert len(g["concepts"]) == 5 and g["truncated"] is True


def test_grounding_map_indexes_both_ends():
    units = [_unit("defines", "x", {"from_key": "居间合同", "to_key": "合同法"})]
    g = _grounding_map(units)
    assert g["居间合同"] == [{"kind": "defines", "other": "合同法", "direction": "out"}]
    assert g["合同法"] == [{"kind": "defines", "other": "居间合同", "direction": "in"}]


@pytest.fixture()
def conn(empty_db):  # noqa: F811
    ensure_schema(db_path=empty_db)
    templates.create_template(conn=empty_db, name="tpl", schema=dict(SCHEMA), created_by="t")
    dom = workspaces.instantiate_domain(
        conn=empty_db, key="legal", name="法律域", template_name="tpl",
        template_version=None, created_by="t",
    )
    workspaces.add_member(conn=empty_db, domain_id=dom["id"], user_id="u1", role="lead",
                          added_by="t")
    empty_db.commit()
    yield empty_db
    from src.eval.db import close_shared_conn
    close_shared_conn()


def test_page_renders_the_graph_and_grounding(conn):
    from src.web.app import create_app
    from src.web.auth import logto
    from src.web.auth.deps import User, get_current_user
    from src.web.deps import get_db

    authoring.authoring_create_unit(conn, domain_key="legal", kind="concept",
                                    external_key="居间合同", body="居间合同", operator="t")
    authoring.authoring_create_unit(conn, domain_key="legal", kind="law",
                                    external_key="合同法", body="中华人民共和国合同法", operator="t")
    authoring.authoring_create_relationship(
        conn, domain_key="legal", kind="defines", from_key="居间合同", to_key="合同法",
        body="居间合同 依据 合同法", operator="t",
    )
    authoring.authoring_create_unit(conn, domain_key="legal", kind="concept",
                                    external_key="举证责任", body="举证责任", operator="t")

    logto.verify_reachable = lambda: None
    app = create_app()
    user = User(sub="u1", name="u1", email="u@e.com", scopes=["*"], channel="test")

    def _cu(request: Request) -> User:
        request.state.user = user
        return user

    app.dependency_overrides[get_db] = lambda: conn
    app.dependency_overrides[get_current_user] = _cu
    with TestClient(app) as c:
        html = c.get("/d/legal/ontology").text
    body = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
    assert 'class="onto-graph__svg"' in body          # the picture is there
    assert "居间合同" in body and "合同法" in body
    assert "未挂依据的单位" in body                     # the gap is named
    assert "举证责任" in body
    assert "grounding" in body or "依据" in body
