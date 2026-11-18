"""Ontology template layering (change add-layered-ontology-templates, task 1-3).

The four rules this file pins:

- ``layer`` is a closed set when declared, and a template that declares nothing
  is its own ``unlayered`` world — every pre-layering template keeps saving
  (there are ~90 of them), yet a legacy template can never inherit into a
  declared layer.
- ``extends`` joins two templates of the SAME layer; crossing layers is refused
  with both layer names in the message, because the fix ("use aligned_with")
  is not discoverable from "invalid".
- ``authority: external`` locks the vocabulary: the owner is elsewhere, and the
  only legal way to change it is to import a new version.
- A word declared both as an entity type and as a relationship kind is refused
  (a role is a relationship), which is what keeps cross-system alignment from
  having to map "customer" to "Acme GmbH".
"""

from __future__ import annotations

import pytest

from src.bench import inheritance, templates
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema


@pytest.fixture()
def db_conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    yield empty_db


def schema(**over) -> dict:
    base = {
        "entity_types": ["organization"],
        "concept_structures": {"organization": ["name"]},
        "relationship_kinds": ["part_of"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {"source_types": []},
    }
    base.update(over)
    return base


# ------------------------------------------------------------------- layers


def test_unknown_layer_is_rejected_and_names_the_closed_set():
    problems = templates.validate_template_schema(schema(layer="vertical"))
    assert problems, "an unknown layer must not save"
    assert "vertical" in problems[0]
    for layer in templates.LAYERS:
        assert layer in problems[0], "the refusal must list every legal layer"


def test_missing_layer_still_saves_as_unlayered():
    # Every template created before this change has no layer; rejecting them
    # would turn a capability addition into a migration of ~90 call sites.
    assert templates.validate_template_schema(schema()) == []
    assert templates.template_layer(schema()) == templates.UNLAYERED


def test_layer_is_read_back_from_the_schema():
    assert templates.template_layer(schema(layer="industry")) == "industry"


def test_external_authority_requires_source_and_version():
    problems = templates.validate_template_schema(
        schema(layer="observation", authority={"kind": "external"})
    )
    assert any("source" in p for p in problems)
    assert any("version" in p for p in problems)


def test_unknown_authority_kind_is_rejected():
    problems = templates.validate_template_schema(schema(authority={"kind": "vendor"}))
    assert any("vendor" in p for p in problems)


def test_external_authority_blocks_in_place_vocabulary_edit(db_conn):
    """Re-saving an external template with a different vocabulary is refused."""
    from src.bench import template_readiness  # noqa: F401  (import path sanity)

    ext = schema(
        layer="observation",
        authority={"kind": "external", "source": "p", "version": "2026.11"},
    )
    templates.create_template(db_conn, name="ext", schema=ext, created_by="t")
    before = templates.get_template(db_conn, name="ext")

    edited = dict(ext)
    edited["entity_types"] = ["organization", "invented_type"]
    # The vocabulary itself is still structurally valid — the refusal must come
    # from the authority rule, not from shape validation.
    assert templates.validate_template_schema(edited) == []

    conn_guard = templates.external_edit_problem(
        existing=before, new_schema=edited
    )
    assert conn_guard is not None
    assert "external" in conn_guard
    # Nothing was written: the stored version still has the original vocabulary.
    after = templates.get_template(db_conn, name="ext")
    assert after["version"] == 1
    assert after["schema"]["entity_types"] == before["schema"]["entity_types"]


def test_platform_authority_allows_edit():
    assert templates.external_edit_problem(
        existing=schema(authority={"kind": "platform"}),
        new_schema=schema(authority={"kind": "platform"}, entity_types=["organization", "x"]),
    ) is None


def test_layer_cannot_change_between_versions():
    problem = templates.layer_change_problem(
        existing=schema(layer="industry"), new_schema=schema(layer="foundation")
    )
    assert problem is not None
    assert "industry" in problem and "foundation" in problem


def test_adopting_a_layer_for_the_first_time_is_the_migration():
    """`unlayered` is the absence of a layer, not a layer — adopting one is legal.

    Without this branch the migration script could never stamp an existing
    template, so the concept could not be rolled out at all.
    """
    assert templates.layer_change_problem(
        existing=schema(), new_schema=schema(layer="domain")
    ) is None


def test_retreating_from_a_layer_to_unlayered_is_refused():
    problem = templates.layer_change_problem(
        existing=schema(layer="domain"), new_schema=schema()
    )
    assert problem is not None
    assert "domain" in problem


# ---------------------------------------------------------------- extends


def test_same_layer_inheritance_unions_vocabularies(db_conn):
    parent = schema(layer="industry", entity_types=["organization"])
    templates.create_template(db_conn, name="parent", schema=parent, created_by="t")
    child = schema(
        layer="industry",
        entity_types=["organization", "warehouse"],
        extends={"name": "parent", "version": 1},
    )
    effective = inheritance.resolve_template_schema(db_conn, child)
    assert set(effective["entity_types"]) == {"organization", "warehouse"}


def test_cross_layer_inheritance_is_refused_naming_both_layers(db_conn):
    parent = schema(layer="foundation", entity_types=["organization"])
    templates.create_template(db_conn, name="foundation-v1", schema=parent, created_by="t")
    child = schema(
        layer="industry",
        extends={"name": "foundation-v1", "version": 1},
    )
    with pytest.raises(inheritance.InheritanceError) as exc:
        inheritance.resolve_template_schema(db_conn, child)
    message = str(exc.value)
    assert "foundation" in message and "industry" in message
    assert "aligned_with" in message, "the refusal must name the legal alternative"


def test_unlayered_cannot_inherit_into_a_declared_layer(db_conn):
    """A legacy template keeps working — but only inside its own layer."""
    legacy = schema()  # no layer
    templates.create_template(db_conn, name="legacy", schema=legacy, created_by="t")
    child = schema(layer="industry", extends={"name": "legacy", "version": 1})
    with pytest.raises(inheritance.InheritanceError):
        inheritance.resolve_template_schema(db_conn, child)


def test_two_unlayered_templates_still_inherit(db_conn):
    """Pre-layering behaviour is preserved byte for byte."""
    templates.create_template(db_conn, name="old-parent", schema=schema(), created_by="t")
    child = schema(entity_types=["organization", "claim"],
                   extends={"name": "old-parent", "version": 1})
    effective = inheritance.resolve_template_schema(db_conn, child)
    assert set(effective["entity_types"]) == {"organization", "claim"}


# ------------------------------------------------------------- alignment


def test_aligned_with_is_read_but_never_merged(db_conn):
    """The mapping is a declaration; the vocabulary stays the template's own."""
    aligned = schema(
        layer="observation",
        entity_types=["company"],
        aligned_with=[
            {
                "target_template": "foundation-v1",
                "target_layer": "foundation",
                "type_map": {"company": "organization"},
            }
        ],
    )
    templates.create_template(db_conn, name="obs", schema=aligned, created_by="t")

    effective = inheritance.resolve_template_schema(db_conn, aligned)
    assert effective["entity_types"] == ["company"], (
        "aligned_with must not add the target's types to this template"
    )

    mapping = inheritance.aligned_types(db_conn, name="obs")
    assert mapping["company"]["aligned_type"] == "organization"
    assert mapping["company"]["target_layer"] == "foundation"


def test_aligned_types_is_empty_for_an_undeclared_type(db_conn):
    templates.create_template(db_conn, name="plain", schema=schema(), created_by="t")
    assert inheritance.aligned_types(db_conn, name="plain") == {}


def test_aligned_with_must_carry_a_type_map():
    problems = templates.validate_template_schema(
        schema(aligned_with=[{"target_template": "foundation-v1"}])
    )
    assert any("type_map" in p for p in problems)


# ---------------------------------------------------------- role vs type


def test_a_word_cannot_be_both_an_entity_type_and_a_relationship():
    problems = templates.validate_template_schema(
        schema(entity_types=["organization", "customer"],
               relationship_kinds=["customer"])
    )
    assert problems
    assert "customer" in problems[0]


def test_role_relationship_alone_is_fine():
    assert templates.validate_template_schema(
        schema(entity_types=["organization"], relationship_kinds=["sells_to", "supplies"])
    ) == []
