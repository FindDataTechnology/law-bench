"""Crosswalk assertions travel the normal proposal path (change add-crosswalk-seam).

The rules are pure and live in ``test_bench_crosswalk.py``; this file pins the
integration that makes them matter — a crosswalk is submitted like anything else,
refused when malformed, and lands as a knowledge unit only after a human confirms
it. If any of that is skipped, the seam would be a second write path, which is
the one thing the ontology kernel forbids.

Three behaviours carry the most weight here:

- a malformed assertion is refused **at submission**, not left for a reviewer to
  discover (occupying a slot teaches the submitter nothing);
- **our endpoint must already exist** — the inbox does not manufacture endpoints,
  same discipline as relationships;
- confirmation writes through the kernel's single path, so the unit and its
  append-only event appear together.
"""

from __future__ import annotations

import pytest

from src.bench import proposals, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema


@pytest.fixture()
def db_conn(empty_db):  # noqa: F811
    ensure_schema(db_path=empty_db)
    yield empty_db


@pytest.fixture()
def domain(db_conn):
    tpl = templates.create_template(
        db_conn,
        name="erp-base",
        schema={
            "entity_types": ["organization", "account"],
            "concept_structures": {},
            "relationship_kinds": ["sells_to"],
            "tier_vocabulary": list(TIERS),
            "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
            "corpus_declaration": {"source_types": []},
            "layer": "industry",
            "authority": {"kind": "platform"},
        },
        created_by="t",
    )
    dom = workspaces.instantiate_domain(
        db_conn, key="erp", name="ERP",
        template_name="erp-base", template_version=tpl["version"], created_by="t",
    )
    db_conn.commit()
    return dom


def _mapping(**over) -> dict:
    base = {
        "relation": "same_as",
        "peer": {"kind": "external_id", "system": "salesforce", "id": "0014x"},
        "confidence": 0.94,
    }
    base.update(over)
    return base


def _submit(db_conn, *, key: str, mapping: dict, source: str = "user:expert-1"):
    return proposals.submit(
        db_conn,
        domain_key="erp",
        source=source,
        kind="crosswalk",
        external_key=key,
        body="映射断言",
        evidence={"mapping": mapping, "quote": "某张表第 3 行"},
        submitted_by="expert-1",
        authenticated_as="expert-1",
    )


# ------------------------------------------------------------------ refusal


def test_malformed_mapping_is_refused_at_submission(db_conn, domain):
    with pytest.raises(proposals.ProposalTargetExists) as exc:
        _submit(db_conn, key="organization:acme", mapping={"relation": "equivalent"})
    assert "equivalent" in str(exc.value)


def test_peer_missing_system_is_refused(db_conn, domain):
    with pytest.raises(proposals.ProposalTargetExists) as exc:
        _submit(
            db_conn, key="organization:acme",
            mapping=_mapping(peer={"kind": "external_id", "id": "x"}),
        )
    assert "system" in str(exc.value)


def test_endpoint_must_already_exist(db_conn, domain):
    """The inbox does not manufacture endpoints — a crosswalk about nothing is a
    promise nobody can keep."""
    with pytest.raises(proposals.ProposalTargetExists) as exc:
        _submit(db_conn, key="organization:ghost", mapping=_mapping())
    assert "ghost" in str(exc.value)


def test_missing_mapping_object_is_refused(db_conn, domain):
    with pytest.raises(proposals.ProposalTargetExists):
        proposals.submit(
            db_conn, domain_key="erp", source="user:e", kind="crosswalk",
            external_key="organization:acme", body="x",
            evidence={"quote": "no mapping here"}, submitted_by="e",
            authenticated_as="e",
        )


# ------------------------------------------------------------------ happy path


def test_crosswalk_lands_only_after_confirmation(db_conn, domain):
    """Submitted → pending (no KU). Confirmed → KU + paired event."""
    from src.bench import store

    # Our endpoint must exist first: an entity unit in this domain.
    from src.bench import authoring

    authoring.authoring_create_unit(
        db_conn, domain_key="erp", kind="organization",
        external_key="organization:acme", body="Acme 公司", operator="expert-1",
    )

    proposal = _submit(db_conn, key="organization:acme", mapping=_mapping())
    assert proposal["state"] == "pending"

    # Nothing entered the ontology yet.
    assert store.get_knowledge_unit(
        db_conn, kind="crosswalk", external_key="organization:acme", namespace="erp"
    ) is None

    confirmed = proposals.confirm(
        db_conn, domain_key="erp", proposal_id=proposal["id"], actor="lead-1",
    )
    assert confirmed["state"] == "confirmed"

    unit = store.get_knowledge_unit(
        db_conn, kind="crosswalk", external_key="organization:acme", namespace="erp"
    )
    assert unit is not None
    assert unit["attrs"]["relation"] == "same_as"
    assert unit["attrs"]["peer"]["system"] == "salesforce"


def test_what_was_reviewed_is_what_lands(db_conn, domain):
    """The attrs on the unit are the mapping the reviewer saw, not a re-derivation."""
    from src.bench import authoring, store

    authoring.authoring_create_unit(
        db_conn, domain_key="erp", kind="organization",
        external_key="organization:beta", body="Beta", operator="e",
    )
    mapping = _mapping(confidence=0.61, relation="role_of")
    p = _submit(db_conn, key="organization:beta", mapping=mapping)
    proposals.confirm(db_conn, domain_key="erp", proposal_id=p["id"], actor="lead-1")

    unit = store.get_knowledge_unit(
        db_conn, kind="crosswalk", external_key="organization:beta", namespace="erp"
    )
    assert unit["attrs"]["confidence"] == 0.61
    assert unit["attrs"]["relation"] == "role_of"
