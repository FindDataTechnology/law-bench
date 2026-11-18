"""Template inheritance + domain-scoped knowledge units (§3).

The two failure modes this pins:

- a child template that *drops* an inherited vocabulary item must be refused at
  save time, and instantiation must validate the **effective** (parent ∪ child)
  schema — a child that validates only its own delta could look fine while
  missing vocabulary its parent guarantees;
- a knowledge unit read must resolve own-namespace first, then walk ancestors,
  and must never see a sibling's units (they are not on the chain).
"""

from __future__ import annotations

import pytest

from src.bench import inheritance, store, templates, workspaces
from src.bench.tiers import TIERS
from src.bench.promotion import SENSITIVITY_LEVELS
from src.eval.store import ensure_schema


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    yield empty_db


def _schema(**over) -> dict:
    base = {
        "entity_types": ["clause"],
        "concept_structures": {"clause": ["id", "body"]},
        "relationship_kinds": ["cites_law"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {"source_types": ["uploaded"]},
    }
    base.update(over)
    return base


# ── template inheritance ─────────────────────────────────────────────────────


def test_child_extends_parent_vocabulary(conn):
    templates.create_template(conn, name="legal-domain", schema=_schema(), created_by="t")
    child = _schema(
        entity_types=["clause", "claim"],
        relationship_kinds=["cites_law", "supports"],
        extends={"name": "legal-domain", "version": 1},
    )
    effective = inheritance.resolve_template_schema(conn, child)
    assert set(effective["entity_types"]) == {"clause", "claim"}
    assert set(effective["relationship_kinds"]) == {"cites_law", "supports"}
    assert "extends" not in effective, "the link is resolved, not carried onward"


def test_child_may_not_drop_inherited_item(conn):
    templates.create_template(conn, name="legal-domain", schema=_schema(), created_by="t")
    child = _schema(
        entity_types=[],  # drops the inherited "clause"
        extends={"name": "legal-domain", "version": 1},
    )
    with pytest.raises(inheritance.InheritanceError, match="may not drop"):
        inheritance.resolve_template_schema(conn, child)


def test_missing_parent_is_an_error_not_an_empty_inheritance(conn):
    with pytest.raises(inheritance.InheritanceError, match="not found"):
        inheritance.resolve_template_schema(
            conn, _schema(extends={"name": "ghost", "version": 1})
        )


def test_effective_validation_catches_broken_parent(conn):
    # A parent whose schema was inserted without validation (legacy row) must
    # not let a child "validate" against it.
    conn.execute(
        "INSERT INTO ontology_templates (name, version, schema, created_by) "
        "VALUES ('broken', 1, '{\"entity_types\":[\"x\"]}', 't')"
    )
    conn.commit()
    # A thin child that leans on the parent: the merged schema is what gets
    # validated, so a broken parent surfaces here instead of at instantiation.
    problems = inheritance.validate_effective(
        conn, {"entity_types": ["x"], "extends": {"name": "broken", "version": 1}}
    )
    assert any("missing required key" in p for p in problems)


def test_parent_version_is_pinned(conn):
    parent = templates.create_template(conn, name="legal-domain", schema=_schema(), created_by="t")
    templates.update_template(
        conn, name="legal-domain", schema=_schema(entity_types=["clause", "law"]), created_by="t"
    )
    child = _schema(
        entity_types=["clause"],
        extends={"name": "legal-domain", "version": parent["version"]},
    )
    effective = inheritance.resolve_template_schema(conn, child)
    assert effective["entity_types"] == ["clause"], "v2's `law` must not leak into a v1-anchored child"


# ── knowledge units ─────────────────────────────────────────────────────────


def _domains(conn):
    tid = conn.execute(
        "SELECT id FROM ontology_templates LIMIT 1"
    ).fetchone()
    if tid is None:
        templates.create_template(conn, name="tpl", schema=_schema(), created_by="t")
        tid = conn.execute("SELECT id FROM ontology_templates LIMIT 1").fetchone()
    tid = tid["id"]
    root = conn.execute(
        "INSERT INTO domains (key,name,template_id,template_version,created_by,path) "
        "VALUES ('legal','Legal',%s,1,'t','legal') RETURNING id, path",
        (tid,),
    ).fetchone()
    child = conn.execute(
        "INSERT INTO domains (key,name,template_id,template_version,created_by,parent_id,path) "
        "VALUES ('cr','CR',%s,1,'t',%s,'legal/cr') RETURNING id, path",
        (tid, root["id"]),
    ).fetchone()
    sibling = conn.execute(
        "INSERT INTO domains (key,name,template_id,template_version,created_by,parent_id,path) "
        "VALUES ('lp','LP',%s,1,'t',%s,'legal/lp') RETURNING id, path",
        (tid, root["id"]),
    ).fetchone()
    conn.commit()
    return dict(root), dict(child), dict(sibling)


def test_unit_resolution_prefers_nearest_namespace(conn):
    root, child, _ = _domains(conn)
    store.upsert_knowledge_unit(
        conn, kind="entity", external_key="party", body="根域定义", namespace=root["path"]
    )
    store.upsert_knowledge_unit(
        conn, kind="entity", external_key="party", body="子域特化", namespace=child["path"]
    )
    got = inheritance.get_unit_inherited(
        conn, kind="entity", external_key="party", domain_path=child["path"]
    )
    assert got["body"] == "子域特化"
    assert got["namespace"] == child["path"]


def test_unit_resolution_falls_back_to_ancestor(conn):
    root, child, _ = _domains(conn)
    store.upsert_knowledge_unit(
        conn, kind="entity", external_key="clause", body="根域定义", namespace=root["path"]
    )
    got = inheritance.get_unit_inherited(
        conn, kind="entity", external_key="clause", domain_path=child["path"]
    )
    assert got["body"] == "根域定义"
    assert got["namespace"] == root["path"]


def test_sibling_units_are_invisible(conn):
    root, child, sibling = _domains(conn)
    store.upsert_knowledge_unit(
        conn, kind="entity", external_key="claim", body="兄弟域", namespace=sibling["path"]
    )
    assert (
        inheritance.get_unit_inherited(
            conn, kind="entity", external_key="claim", domain_path=child["path"]
        )
        is None
    )
    listed = inheritance.list_units_inherited(conn, domain_path=child["path"])
    assert listed == []


def test_list_shadows_and_never_duplicates(conn):
    root, child, _ = _domains(conn)
    store.upsert_knowledge_unit(
        conn, kind="entity", external_key="party", body="根", namespace=root["path"]
    )
    store.upsert_knowledge_unit(
        conn, kind="relationship", external_key="cites", body="根关系", namespace=root["path"]
    )
    store.upsert_knowledge_unit(
        conn, kind="entity", external_key="party", body="子", namespace=child["path"]
    )
    listed = inheritance.list_units_inherited(conn, domain_path=child["path"])
    by_key = {(r["kind"], r["external_key"]): r for r in listed}
    assert len(listed) == 2, "shadowed duplicate must collapse to one row"
    assert by_key[("entity", "party")]["body"] == "子"
    assert by_key[("relationship", "cites")]["namespace"] == root["path"]
