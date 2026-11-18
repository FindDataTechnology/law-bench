"""Ontology-template store (add-ontology-template-and-workspaces, task 4.1).

Covers the template three-piece structural validation and versioning:
- a valid template saves as v1 and shows up in the template list;
- validate_template_schema names each missing required key, non-list
  vocabularies, wrong tier/sensitivity vocabularies (must equal the kernel's
  canonical tuples) and non-dict concept_structures/corpus_declaration;
- create_template refuses invalid/duplicate input with no row inserted;
- update_template appends versions and never rewrites history (v1 keeps its
  original schema content and created_at);
- get_template latest/specific-version lookup and get_template_by_id
  round-trip;
- a domain instantiated from v2 keeps showing template_version=2 even after
  the template moves on to v3 (spec: 实例锚定创建版本).
"""

from __future__ import annotations

import json

import pytest

from src.bench import templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema


@pytest.fixture()
def db_conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    # Inject the fixture's own connection so DDL lands on the per-test DB
    # instead of the process-wide cached shared connection (which stays bound
    # to whichever test DB connected first).
    ensure_schema(db_path=empty_db)
    yield empty_db


def valid_schema() -> dict:
    """A structurally complete template schema (three-piece + four vocabularies)."""
    return {
        "entity_types": ["clause", "party", "obligation"],
        "concept_structures": {
            "contract_lifecycle": {"members": ["draft", "review", "sign"]}
        },
        "relationship_kinds": ["references", "obligates"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {"source_types": ["uploaded"], "granularity": "clause"},
    }


def _count(conn, table: str, where: str = "", params: tuple = ()) -> int:
    row = conn.execute(
        f"SELECT COUNT(*) AS n FROM {table} {where}", params
    ).fetchone()
    return row["n"]


# ------------------------------------------------------------- happy path


def test_valid_template_creates_v1_and_appears_in_list(db_conn):
    schema = valid_schema()
    created = templates.create_template(
        db_conn, name="legal-tpl", schema=schema, created_by="admin-1"
    )

    assert created["name"] == "legal-tpl"
    assert created["version"] == 1
    assert created["schema"] == schema  # decoded JSONB round-trips as a dict
    assert created["created_by"] == "admin-1"
    assert created["created_at"]  # timestamp present
    assert set(created.keys()) == {
        "id",
        "name",
        "version",
        "schema",
        "created_by",
        "created_at",
    }

    # spec (合法模板可保存并展示): shows up in the template list, latest version
    listed = templates.list_templates(db_conn)
    assert [t["name"] for t in listed] == ["legal-tpl"]
    assert listed[0]["version"] == 1
    assert listed[0]["schema"] == schema

    # exactly one physical row
    assert _count(db_conn, "ontology_templates") == 1


# --------------------------------------------------- structural validation


def test_validate_schema_names_every_missing_required_key(db_conn):
    # A completely empty dict reports one problem per required key, each naming it.
    problems = templates.validate_template_schema({})
    for key in templates.REQUIRED_SCHEMA_KEYS:
        assert f"missing required key: {key}" in problems

    # Removing exactly one key from a valid schema yields exactly that one problem.
    for key in templates.REQUIRED_SCHEMA_KEYS:
        broken = valid_schema()
        del broken[key]
        problems = templates.validate_template_schema(broken)
        assert problems == [f"missing required key: {key}"], key


def test_validate_schema_rejects_non_list_vocabulary(db_conn):
    for key in ("entity_types", "relationship_kinds", "tier_vocabulary",
                "sensitivity_vocabulary"):
        broken = valid_schema()
        broken[key] = "clause, party"  # a string, not a list
        problems = templates.validate_template_schema(broken)
        assert f"{key} must be a non-empty list of strings" in problems, key

    # empty list and non-string items are also refused
    broken = valid_schema()
    broken["entity_types"] = []
    assert "entity_types must be a non-empty list of strings" in (
        templates.validate_template_schema(broken)
    )
    broken = valid_schema()
    broken["relationship_kinds"] = ["ok", 7]
    assert "relationship_kinds must be a non-empty list of strings" in (
        templates.validate_template_schema(broken)
    )


def test_validate_schema_rejects_wrong_tier_vocabulary(db_conn):
    broken = valid_schema()
    broken["tier_vocabulary"] = ["gold", "silver", "bronze"]  # missing "raw"
    problems = templates.validate_template_schema(broken)
    assert any(
        "tier_vocabulary" in p and list(TIERS)[0] in p for p in problems
    ), problems
    # and create refuses it
    with pytest.raises(ValueError, match="tier_vocabulary"):
        templates.create_template(
            db_conn, name="bad-tiers", schema=broken, created_by="admin-1"
        )


def test_validate_schema_rejects_wrong_sensitivity_vocabulary(db_conn):
    broken = valid_schema()
    broken["sensitivity_vocabulary"] = ["public", "internal"]  # missing confidential
    problems = templates.validate_template_schema(broken)
    assert any("sensitivity_vocabulary" in p for p in problems), problems
    assert any(
        all(level in p for level in SENSITIVITY_LEVELS) for p in problems
    ), problems


def test_validate_schema_rejects_concept_structures_not_dict(db_conn):
    broken = valid_schema()
    broken["concept_structures"] = ["contract_lifecycle"]  # a list, not a dict
    problems = templates.validate_template_schema(broken)
    assert problems == ["concept_structures must be a dict"]


def test_validate_schema_rejects_corpus_declaration_not_dict(db_conn):
    broken = valid_schema()
    broken["corpus_declaration"] = "see docs"  # a string, not a dict
    problems = templates.validate_template_schema(broken)
    assert problems == ["corpus_declaration must be a dict"]


# ----------------------------------------------------- create_template refusals


def test_create_template_invalid_schema_raises_joined_message_and_inserts_nothing(db_conn):
    broken = valid_schema()
    del broken["tier_vocabulary"]
    del broken["corpus_declaration"]
    broken["entity_types"] = []

    with pytest.raises(ValueError) as exc:
        templates.create_template(
            db_conn, name="broken-tpl", schema=broken, created_by="admin-1"
        )
    message = str(exc.value)
    # problems are joined into one message, each named
    assert "missing required key: tier_vocabulary" in message
    assert "missing required key: corpus_declaration" in message
    assert "entity_types must be a non-empty list of strings" in message

    # no row inserted
    assert _count(db_conn, "ontology_templates") == 0


def test_create_template_duplicate_name_raises_and_no_second_row(db_conn):
    templates.create_template(
        db_conn, name="dup-tpl", schema=valid_schema(), created_by="admin-1"
    )
    with pytest.raises(ValueError, match="already exists"):
        templates.create_template(
            db_conn,
            name="dup-tpl",
            schema={**valid_schema(), "entity_types": ["other"]},
            created_by="admin-2",
        )
    # still exactly one row for that name, still v1 with the ORIGINAL schema
    assert _count(db_conn, "ontology_templates", "WHERE name = %s", ("dup-tpl",)) == 1
    only = templates.get_template(db_conn, name="dup-tpl")
    assert only["version"] == 1
    assert only["schema"] == valid_schema()
    assert only["created_by"] == "admin-1"  # second create did not touch it


# ------------------------------------------------------------- versioning


def test_update_template_appends_versions_and_never_rewrites_history(db_conn):
    v1_schema = valid_schema()
    v1 = templates.create_template(
        db_conn, name="evolving-tpl", schema=v1_schema, created_by="admin-1"
    )
    v1_created_at = v1["created_at"]

    v2_schema = {**valid_schema(), "entity_types": ["clause", "party", "remedy"]}
    v2 = templates.update_template(
        db_conn, name="evolving-tpl", schema=v2_schema, created_by="admin-1"
    )
    v3_schema = {**valid_schema(), "relationship_kinds": ["references"]}
    v3 = templates.update_template(
        db_conn, name="evolving-tpl", schema=v3_schema, created_by="admin-2"
    )
    assert (v2["version"], v3["version"]) == (2, 3)

    versions = templates.list_template_versions(db_conn, name="evolving-tpl")
    assert [v["version"] for v in versions] == [1, 2, 3]
    # history is append-only: v1 keeps its ORIGINAL schema content and created_at
    assert versions[0]["schema"] == v1_schema
    assert versions[0]["created_at"] == v1_created_at
    assert versions[0]["created_by"] == "admin-1"
    assert versions[1]["schema"] == v2_schema
    assert versions[2]["schema"] == v3_schema
    assert versions[2]["created_by"] == "admin-2"

    # nothing was rewritten in place: 3 physical rows, distinct ids
    assert _count(db_conn, "ontology_templates", "WHERE name = %s", ("evolving-tpl",)) == 3
    assert len({v["id"] for v in versions}) == 3
    assert {v1["id"], v2["id"], v3["id"]} == {v["id"] for v in versions}


def test_update_template_invalid_schema_refused_and_appends_nothing(db_conn):
    templates.create_template(
        db_conn, name="stable-tpl", schema=valid_schema(), created_by="admin-1"
    )
    with pytest.raises(ValueError, match="missing required key: tier_vocabulary"):
        templates.update_template(
            db_conn,
            name="stable-tpl",
            schema={k: v for k, v in valid_schema().items() if k != "tier_vocabulary"},
            created_by="admin-1",
        )
    versions = templates.list_template_versions(db_conn, name="stable-tpl")
    assert [v["version"] for v in versions] == [1]  # no version appended


# ---------------------------------------------------------------- lookups


def test_get_template_latest_and_specific_version(db_conn):
    v1 = templates.create_template(
        db_conn, name="lookup-tpl", schema=valid_schema(), created_by="admin-1"
    )
    v2_schema = {**valid_schema(), "entity_types": ["only-one"]}
    v2 = templates.update_template(
        db_conn, name="lookup-tpl", schema=v2_schema, created_by="admin-1"
    )

    latest = templates.get_template(db_conn, name="lookup-tpl")
    assert latest["id"] == v2["id"]
    assert latest["version"] == 2
    assert latest["schema"] == v2_schema

    first = templates.get_template(db_conn, name="lookup-tpl", version=1)
    assert first["id"] == v1["id"]
    assert first["version"] == 1
    assert first["schema"] == valid_schema()

    assert templates.get_template(db_conn, name="lookup-tpl", version=99) is None
    assert templates.get_template(db_conn, name="ghost-tpl") is None


def test_get_template_by_id_round_trips(db_conn):
    created = templates.create_template(
        db_conn, name="by-id-tpl", schema=valid_schema(), created_by="admin-1"
    )
    fetched = templates.get_template_by_id(db_conn, template_id=created["id"])
    assert fetched == created
    assert templates.get_template_by_id(db_conn, template_id=created["id"] + 10**6) is None


# --------------------------------------------- domain anchoring (实例锚定)


def test_domain_anchored_to_v2_stays_v2_after_template_reaches_v3(db_conn):
    templates.create_template(
        db_conn, name="anchor-tpl", schema=valid_schema(), created_by="admin-1"
    )
    v2 = templates.update_template(
        db_conn,
        name="anchor-tpl",
        schema={**valid_schema(), "entity_types": ["v2-entity"]},
        created_by="admin-1",
    )

    domain = workspaces.instantiate_domain(
        db_conn,
        key="dom-anchor",
        name="Anchored Domain",
        template_name="anchor-tpl",
        template_version=2,
        created_by="admin-1",
    )
    assert domain["template_id"] == v2["id"]
    assert domain["template_version"] == 2

    # template moves on to v3 after instantiation
    v3 = templates.update_template(
        db_conn,
        name="anchor-tpl",
        schema={**valid_schema(), "entity_types": ["v3-entity"]},
        created_by="admin-1",
    )
    assert v3["version"] == 3

    # the domain's anchor is untouched: still v2, still the v2 row
    fetched = workspaces.get_domain(db_conn, domain_key="dom-anchor")
    assert fetched["template_id"] == v2["id"]
    assert fetched["template_version"] == 2

    anchored_row = templates.get_template_by_id(db_conn, template_id=domain["template_id"])
    assert anchored_row["version"] == 2
    assert anchored_row["schema"] == v2["schema"]  # v2 content intact, not retroactively v3
