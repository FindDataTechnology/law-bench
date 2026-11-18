"""The judge's grading call must actually receive the structure rules.

Regression guard for a defect measured on 2026-11-11: deepeval 3.9.6's strict
template asks the model for a JSON with exactly ``score`` and ``reason``
("no words or explanation is needed"). When only ``criteria`` is supplied,
deepeval generates the evaluation steps itself, the ``CONFIDENCE: <0.xx>``
self-report never reaches the grading prompt, and every passing verdict comes
back unsigned — ``classify_structural_soundness`` then marks it
``contract_violation``, i.e. **10/10 invalid and a score of 0.0 for every
contract**. A ruler that can only return "invalid" is as useless as one that is
always green, and nothing in the suite went red while it happened.

So these tests pin the three things that make the verdicts verifiable:

- the steps handed to GEval carry the criterion's own guidance and the
  ``CONFIDENCE`` requirement (``build_evaluation_steps``);
- ``_build_metrics`` passes those steps to every GEval (not just ``criteria``);
- an unsigned pass is re-measured instead of being dropped
  (``needs_self_report_retry`` + the retry path in ``evaluate_contract``).

No network: the retry test drives the real aggregation path with FakeJudge.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import src.eval.scoring as scoring
from _fakes import FakeJudge
from src.eval.scoring import (
    build_evaluation_steps,
    evaluate_contract,
    needs_self_report_retry,
)

_RUBRIC = "l_rubric"  # seeded with criteria c1, c2 (see conftest)


@pytest.fixture(autouse=True)
def _no_prompt_domain(monkeypatch):
    """Keep the structure-rules lookup on its documented constant fallback.

    ``build_evaluation_steps`` reads the rules from the prompt domain and falls
    back to the module constant when the row is missing. Letting that lookup run
    for real is not free: it opens the process-wide *shared* connection, and if
    it is the first DB touch in the process it pins that connection to whatever
    ``database_url`` says at that moment (the developer DB, before the session
    fixture repoints it). The session DB then silently never gets its schema and
    ``seed_db`` fails on its first missing table — measured here as
    ``relation "review_tasks" does not exist`` in fixture setup only.
    """
    monkeypatch.setattr(scoring, "_load_judge_rules_from_domain", lambda *a, **k: None)


# --- the steps carry the rules ---------------------------------------------- #


def test_steps_carry_the_criterion_guidance():
    steps = build_evaluation_steps("PASS if 主体列明；FAIL if 未列明。")
    assert any("PASS if 主体列明" in s for s in steps), steps


def test_steps_demand_the_confidence_self_report():
    """Without this the model never emits the marker (measured 2026-11-11)."""
    steps = build_evaluation_steps("PASS if A; FAIL if B.")
    assert any("CONFIDENCE" in s for s in steps), steps


def test_steps_forbid_reading_the_verdict_out_of_the_document():
    steps = build_evaluation_steps("PASS if A; FAIL if B.")
    joined = " ".join(steps)
    assert "Never look for PASS/FAIL markers" in joined
    assert "content under evaluation" in joined


def test_every_geval_receives_explicit_steps(seeded_db: Path):
    """criteria alone is what deepeval reduces to a model-generated step list."""
    metrics = scoring._build_metrics(
        [{"id": "c1", "title": "t1", "match_criteria": "PASS if A; FAIL if B."}],
        FakeJudge(verdicts=[True]),
        include_input=False,
        db_path=seeded_db,
    )
    steps = metrics[0].evaluation_steps
    assert steps, "evaluation_steps must be explicit; generated steps lose the marker rule"
    assert any("CONFIDENCE" in s for s in steps)


# --- the retry rule --------------------------------------------------------- #


def test_an_unsigned_pass_is_retried():
    assert needs_self_report_retry(True, "no self report here") is True


def test_a_signed_pass_is_not_retried():
    assert needs_self_report_retry(True, "…结论。CONFIDENCE: 0.87") is False


def test_a_fail_is_never_retried():
    """A fail is already excluded from n_passed; retrying it buys nothing."""
    assert needs_self_report_retry(False, "no self report here") is False


# --- the retry actually runs, end to end ------------------------------------ #


def test_an_unsigned_pass_is_re_measured_until_it_is_signed(seeded_db: Path):
    """First answer unsigned, second signed: the verdict must end up a valid pass.

    This is the exact failure the run hit: unsigned passes were being recorded
    as ``invalid`` even though the judge's reasoning was correct.
    """
    judge = FakeJudge(verdicts=[
        {"success": True, "reason": "对得上，但没有自证行"},
        {"success": True, "reason": "对得上。CONFIDENCE: 0.93"},
    ])
    res = evaluate_contract(
        "合同正文", _RUBRIC, judge=judge, max_workers=1, db_path=seeded_db,
    )
    first = res["criteria_results"][0]
    assert first["verdict"] == "pass", first
    assert "CONFIDENCE" in first["reasoning"]
