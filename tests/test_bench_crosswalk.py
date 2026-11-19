"""Crosswalk assertion rules (change add-crosswalk-seam, tasks 1.1-1.3).

These are pure-function tests: a crosswalk is validated from a dict, so no
database is needed to pin the rules. The rules that matter most:

- the relation and peer kinds are **closed sets** — a typo is refused with the
  legal set named, never mapped onto "something similar";
- a peer shape carries exactly the fields its kind promises;
- "ok" without evidence is refused, because that is a state nobody can check;
- absent confidence fails closed (counts as unreviewed), which is what keeps
  coverage from being inflated by rows still awaiting review.
"""

from __future__ import annotations

import pytest

from src.bench import crosswalk


def attrs(**over) -> dict:
    base = {
        "relation": "same_as",
        "peer": {"kind": "external_id", "system": "salesforce", "id": "0014x"},
        "confidence": 0.94,
    }
    base.update(over)
    return base


# ------------------------------------------------------------------ relations


def test_known_relations_are_accepted():
    for relation in crosswalk.RELATIONS:
        assert crosswalk.validate_crosswalk(attrs(relation=relation)) == []


def test_unknown_relation_is_refused_naming_the_closed_set():
    problems = crosswalk.validate_crosswalk(attrs(relation="equivalent"))
    assert problems
    assert "equivalent" in problems[0]
    for relation in crosswalk.RELATIONS:
        assert relation in problems[0]


def test_the_three_relations_are_the_declared_set():
    assert crosswalk.RELATIONS == ("same_as", "role_of", "maps_to")


# ---------------------------------------------------------------------- peers


def test_external_id_peer_requires_system_and_id():
    problems = crosswalk.validate_crosswalk(
        attrs(peer={"kind": "external_id", "id": "BD001"})
    )
    assert any("system" in p for p in problems)


def test_ontology_peer_requires_layer_ref_and_endpoint():
    problems = crosswalk.validate_crosswalk(
        attrs(peer={"kind": "ontology", "endpoint": "company:acme"})
    )
    assert any("layer_ref" in p for p in problems)


def test_ontology_peer_endpoint_must_be_type_colon_key():
    problems = crosswalk.validate_crosswalk(
        attrs(peer={"kind": "ontology", "layer_ref": "external-world-2026.11",
                    "endpoint": "acme"})
    )
    assert any("<type>:<key>" in p for p in problems)


def test_unknown_peer_kind_is_refused():
    problems = crosswalk.validate_crosswalk(attrs(peer={"kind": "url", "id": "x"}))
    assert any("url" in p for p in problems)


def test_both_peer_shapes_validate():
    assert crosswalk.validate_crosswalk(
        attrs(peer={"kind": "ontology", "layer_ref": "external-world-2026.11",
                    "endpoint": "company:acme-corp"})
    ) == []


# ---------------------------------------------------------------- confidence


def test_confidence_out_of_range_is_refused():
    assert crosswalk.validate_crosswalk(attrs(confidence=1.5))
    assert crosswalk.validate_crosswalk(attrs(confidence=-0.1))
    assert crosswalk.validate_crosswalk(attrs(confidence="high"))


def test_absent_confidence_is_not_a_validation_error_but_fails_closed():
    """It is legal to omit it — and it then counts as unreviewed, not as fine."""
    assert crosswalk.validate_crosswalk(attrs(confidence=None)) == []
    assert crosswalk.is_confirmed({"confidence": None}, threshold=0.8) is False
    assert crosswalk.is_confirmed({}, threshold=None) is False


def test_confirmed_requires_meeting_the_threshold():
    assert crosswalk.is_confirmed({"confidence": 0.9}, threshold=0.8) is True
    assert crosswalk.is_confirmed({"confidence": 0.4}, threshold=0.8) is False
    # No threshold declared anywhere: a number is enough to count as reviewed.
    assert crosswalk.is_confirmed({"confidence": 0.1}, threshold=None) is True


# -------------------------------------------------------------- connectivity


def test_three_state_evidence_shape():
    good = {
        "catalog": {"ok": True, "evidence": "catalog/apps/shopify_admin.json"},
        "executor_tests": {"ok": True, "evidence": "providers/shopify_admin/*.test.ts"},
        "live": {"ok": True, "evidence": "acceptance 2026-11-12"},
    }
    assert crosswalk.validate_crosswalk(attrs(connectivity=good)) == []
    assert crosswalk.is_connectivity_complete(good) is True


def test_missing_live_state_is_not_connected():
    """Two out of three does not make a system reachable."""
    partial = {
        "catalog": {"ok": True, "evidence": "a"},
        "executor_tests": {"ok": True, "evidence": "b"},
    }
    assert crosswalk.validate_crosswalk(attrs(connectivity=partial)) == []
    assert crosswalk.is_connectivity_complete(partial) is False
    assert crosswalk.missing_connectivity_states(partial) == ["live"]


def test_ok_without_evidence_is_refused():
    """The exact failure the discipline exists to prevent: a state nobody checks."""
    problems = crosswalk.validate_crosswalk(
        attrs(connectivity={"live": {"ok": True, "evidence": None}})
    )
    assert any("no evidence" in p for p in problems)


def test_unknown_connectivity_state_is_refused():
    problems = crosswalk.validate_crosswalk(
        attrs(connectivity={"smoke": {"ok": True, "evidence": "x"}})
    )
    assert any("smoke" in p for p in problems)


def test_no_connectivity_means_all_states_missing():
    assert crosswalk.missing_connectivity_states(None) == list(
        crosswalk.CONNECTIVITY_STATES
    )


# -------------------------------------------------------------------- keys


def test_crosswalk_key_is_type_colon_key():
    assert crosswalk.crosswalk_key("customer", "acme") == "customer:acme"


def test_crosswalk_key_requires_both_parts():
    with pytest.raises(crosswalk.CrosswalkError):
        crosswalk.crosswalk_key("customer", "  ")


# ------------------------------------------------------------------ expiry


def test_expired_evidence_counts_as_missing():
    """'We checked it once, in March' is not a live connection."""
    old = {
        state: {"ok": True, "evidence": f"p-{state}", "at": "2020-01-01T00:00:00Z"}
        for state in crosswalk.CONNECTIVITY_STATES
    }
    assert crosswalk.expired_states(old, max_age_days=30) == list(
        crosswalk.CONNECTIVITY_STATES
    )
    assert crosswalk.effective_missing_states(old, max_age_days=30) == list(
        crosswalk.CONNECTIVITY_STATES
    )


def test_fresh_evidence_does_not_expire():
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    fresh = {
        state: {"ok": True, "evidence": f"p-{state}", "at": now}
        for state in crosswalk.CONNECTIVITY_STATES
    }
    assert crosswalk.expired_states(fresh, max_age_days=30) == []
    assert crosswalk.effective_missing_states(fresh, max_age_days=30) == []


def test_no_declared_max_age_means_nothing_expires():
    """A domain that declared no expiry must not have one invented for it."""
    old = {s: {"ok": True, "evidence": "p", "at": "2020-01-01T00:00:00Z"}
           for s in crosswalk.CONNECTIVITY_STATES}
    assert crosswalk.expired_states(old, max_age_days=None) == []


def test_missing_and_expired_are_unioned_in_order():
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    mixed = {
        "catalog": {"ok": True, "evidence": "p", "at": "2020-01-01T00:00:00Z"},
        "executor_tests": {"ok": True, "evidence": "p", "at": now},
        # live absent entirely
    }
    assert crosswalk.effective_missing_states(mixed, max_age_days=30) == [
        "catalog", "live",
    ]
