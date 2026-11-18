"""Contract tests for the verdict-ledger vocabulary (add-eval-verdict-ledger).

Pure-function tests: no DB, no LLM, no network. They exist because the gate and
outcome vocabularies are the ONE thing every product line must agree on — if a
typo silently lands an unknown gate in the ledger, cross-line trends stop being
comparable and nothing raises.
"""

from __future__ import annotations

import pytest

from src.bench import verdicts


def _kw(**over):
    base = dict(
        subject_kind="contract",
        subject_key="sale/v1",
        subject_version="sha256:abc",
        ruler_kind="rubric",
        ruler_key="contract_sale_v1",
        ruler_digest="deadbeef",
        gate="all-pass",
        outcome="pass",
    )
    base.update(over)
    return base


# --- the closed sets -------------------------------------------------------


def test_four_gates_and_three_outcomes():
    assert verdicts.GATES == {"no-worse", "regression", "all-pass", "calibrated"}
    assert verdicts.OUTCOMES == {"pass", "fail", "inconclusive"}


def test_unknown_gate_is_rejected_with_the_closed_set_named():
    msg = verdicts.verdict_problem(**_kw(gate="better-than"))
    assert msg is not None
    assert "better-than" in msg
    # the refusal must name every legal value, not just say "invalid"
    for gate in verdicts.GATES:
        assert gate in msg


def test_unknown_outcome_is_rejected():
    msg = verdicts.verdict_problem(**_kw(outcome="unknown"))
    assert msg is not None and "unknown" in msg


@pytest.mark.parametrize("gate", sorted(verdicts.GATES))
def test_every_legal_gate_is_accepted(gate):
    assert verdicts.verdict_problem(**_kw(gate=gate)) is None


@pytest.mark.parametrize("outcome", sorted(verdicts.OUTCOMES))
def test_every_legal_outcome_is_accepted(outcome):
    assert verdicts.verdict_problem(**_kw(outcome=outcome)) is None


# --- identity is mandatory -------------------------------------------------


@pytest.mark.parametrize(
    "field",
    ["subject_kind", "subject_key", "subject_version", "ruler_kind", "ruler_key", "ruler_digest"],
)
def test_missing_identity_field_is_named_in_the_refusal(field):
    msg = verdicts.verdict_problem(**_kw(**{field: None}))
    assert msg is not None and field in msg


def test_blank_string_identity_is_a_missing_field():
    """An empty string is not an identity — it is an absent one wearing a hat."""
    msg = verdicts.verdict_problem(**_kw(subject_version="   "))
    assert msg is not None and "subject_version" in msg


def test_legacy_writer_may_skip_identity_but_not_vocabulary():
    assert verdicts.verdict_problem(
        subject_kind=None, subject_key=None, subject_version=None,
        ruler_kind=None, ruler_key=None, ruler_digest=None,
        gate=None, outcome=None, require_identity=False,
    ) is None
    # ...but a bogus gate is still refused even for a legacy writer
    assert verdicts.verdict_problem(
        subject_kind=None, subject_key=None, subject_version=None,
        ruler_kind=None, ruler_key=None, ruler_digest=None,
        gate="nope", outcome=None, require_identity=False,
    ) is not None


# --- comparability ---------------------------------------------------------


def test_first_evaluation_only_establishes_a_baseline():
    verdict = verdicts.comparable("d1", None)
    assert verdict["status"] == "no-baseline"
    assert verdict["comparable"] is False


def test_same_ruler_is_comparable():
    assert verdicts.comparable("d1", "d1") == {"status": "comparable", "comparable": True}


def test_different_ruler_is_a_migration_not_a_comparison():
    verdict = verdicts.comparable("d2", "d1")
    assert verdict["status"] == "ruler-migrated"
    assert verdict["comparable"] is False


def test_unlabeled_ruler_never_counts_as_the_same_ruler():
    """A missing digest must not silently pass as 'same ruler'."""
    assert verdicts.comparable(None, "d1")["status"] == "ruler-migrated"
    assert verdicts.comparable("d1", None)["status"] == "no-baseline"


# --- judge trust is derived, never configured ------------------------------


def test_provisional_when_no_calibration_record_exists():
    assert verdicts.provisional("glm-5.2", "v2", fetch_latest=lambda _k: None) is True


def test_not_provisional_when_latest_calibration_passed():
    row = {"gate": "calibrated", "outcome": "pass"}
    assert verdicts.provisional("glm-5.2", "v2", fetch_latest=lambda _k: row) is False


@pytest.mark.parametrize("outcome", ["fail", "inconclusive"])
def test_provisional_when_latest_calibration_did_not_pass(outcome):
    row = {"gate": "calibrated", "outcome": outcome}
    assert verdicts.provisional("glm-5.2", "v2", fetch_latest=lambda _k: row) is True


def test_deterministic_channel_has_no_judge_to_distrust():
    """A checker-based verdict is not provisional — there is no judge in it."""
    assert verdicts.provisional(None, None, fetch_latest=lambda _k: None) is False


def test_judge_subject_key_distinguishes_prompt_versions():
    assert verdicts.judge_subject_key("glm-5.2", "v2") == "glm-5.2@v2"
    assert verdicts.judge_subject_key("glm-5.2", None) == "glm-5.2@-"
    assert verdicts.judge_subject_key("glm-5.2", "v2") != verdicts.judge_subject_key("glm-5.2", "v3")
