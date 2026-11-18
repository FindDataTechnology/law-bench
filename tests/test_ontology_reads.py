"""Read side of the ontology authoring surface (§1).

Three reads the page and the importer share — they must agree about what
"exists", otherwise a relation can be created against an entity the picker
showed but the resolver rejects.
"""

from __future__ import annotations

import pytest

from src.bench import authoring, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema

SCHEMA = {
    "entity_types": ["clause", "party"],
    "concept_structures": {"clause": ["id"]},
    "relationship_kinds": ["cites", "belongs_to"],
    "tier_vocabulary": list(TIERS),
    "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
    "corpus_declaration": {"source_types": []},
}


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    templates.create_template(conn=empty_db, name="tpl", schema=dict(SCHEMA), created_by="t")
    workspaces.instantiate_domain(
        conn=empty_db, key="legal", name="法律域", template_name="tpl",
        template_version=None, created_by="t",
    )
    yield empty_db
    from src.eval.db import close_shared_conn
    close_shared_conn()


def _unit(conn, kind, key, body="b", **kw):
    return authoring.authoring_create_unit(
        conn, domain_key="legal", kind=kind, external_key=key, body=body, operator="t", **kw
    )


def test_list_filters_by_kind(conn):
    _unit(conn, "clause", "c1")
    _unit(conn, "clause", "c2")
    _unit(conn, "party", "p1")
    assert len(authoring.authoring_list_units(conn, domain_key="legal", kind="clause")) == 2
    assert len(authoring.authoring_list_units(conn, domain_key="legal", kind="party")) == 1


def test_list_filters_by_query_over_key_and_body(conn):
    _unit(conn, "clause", "gb-50011", body="建筑设计防火规范")
    _unit(conn, "clause", "other", body="unrelated")
    assert [u["external_key"] for u in
            authoring.authoring_list_units(conn, domain_key="legal", query="50011")] == ["gb-50011"]
    assert [u["external_key"] for u in
            authoring.authoring_list_units(conn, domain_key="legal", query="防火")] == ["gb-50011"]


def test_deleted_are_hidden_unless_asked(conn):
    _unit(conn, "clause", "live")
    _unit(conn, "clause", "gone")
    authoring.authoring_delete_unit(
        conn, domain_key="legal", kind="clause", external_key="gone", operator="t"
    )
    live = authoring.authoring_list_units(conn, domain_key="legal")
    everything = authoring.authoring_list_units(
        conn, domain_key="legal", include_deleted=True
    )
    assert [u["external_key"] for u in live] == ["live"]
    assert {u["external_key"] for u in everything} == {"live", "gone"}


def test_limit_means_newest_n_matching_not_newest_n_then_filter(conn):
    """Filtering after a LIMIT returned a short page that looked empty."""
    for i in range(5):
        _unit(conn, "party", f"p{i}")
    _unit(conn, "clause", "c1")
    got = authoring.authoring_list_units(conn, domain_key="legal", kind="clause", limit=1)
    assert [u["external_key"] for u in got] == ["c1"]


def test_live_entities_excludes_deleted_and_relations(conn):
    _unit(conn, "clause", "c1")
    _unit(conn, "clause", "c2")
    _unit(conn, "party", "p1")
    authoring.authoring_create_relationship(
        conn, domain_key="legal", kind="cites", from_key="c1", to_key="c2",
        body="cites", operator="t",
    )
    authoring.authoring_delete_unit(
        conn, domain_key="legal", kind="party", external_key="p1", operator="t"
    )
    keys = {e["external_key"] for e in authoring.authoring_live_entities(conn, domain_key="legal")}
    assert keys == {"c1", "c2"}          # deleted entity and all relations excluded


def test_detail_lists_relations_from_both_ends(conn):
    _unit(conn, "clause", "c1")
    _unit(conn, "clause", "c2")
    authoring.authoring_create_relationship(
        conn, domain_key="legal", kind="cites", from_key="c1", to_key="c2",
        body="cites", operator="t",
    )
    for key, other in (("c1", "c2"), ("c2", "c1")):
        detail = authoring.authoring_unit_detail(
            conn, domain_key="legal", kind="clause", external_key=key
        )
        assert len(detail["related"]) == 1
        assert detail["related"][0]["other"] == other


def test_detail_marks_a_dangling_relation(conn):
    _unit(conn, "clause", "c1")
    _unit(conn, "clause", "c2")
    authoring.authoring_create_relationship(
        conn, domain_key="legal", kind="cites", from_key="c1", to_key="c2",
        body="cites", operator="t",
    )
    authoring.authoring_delete_unit(
        conn, domain_key="legal", kind="clause", external_key="c2", operator="t"
    )
    detail = authoring.authoring_unit_detail(
        conn, domain_key="legal", kind="clause", external_key="c1"
    )
    assert detail["related"][0]["dangling"] is True
