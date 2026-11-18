"""Unit tests for ``src/eval/scoring.py`` using an injected FakeJudge (no network).

All calls use ``max_workers=1`` so the FakeJudge's verdict queue is consumed in
criteria order (see tests/_fakes.py). ``db_path`` points at the throwaway DB so
the development database is never touched.
"""

from __future__ import annotations

from pathlib import Path

from _fakes import FakeJudge
from src.eval.scoring import evaluate_contract

_RUBRIC = "l_rubric"  # seeded with criteria c1, c2


def _eval(seeded_db: Path, verdicts: list, **judge_kw) -> dict:
    return evaluate_contract(
        "合同正文",
        _RUBRIC,
        judge=FakeJudge(verdicts=verdicts, **judge_kw),
        max_workers=1,
        db_path=seeded_db,
    )


def test_all_pass(seeded_db: Path):
    res = _eval(seeded_db, [True, True])
    assert res["all_pass"] is True
    assert res["score"] == 1.0
    assert res["n_passed"] == 2
    assert res["n_criteria"] == 2
    assert all(cr["verdict"] == "pass" for cr in res["criteria_results"])


def test_partial_fail(seeded_db: Path):
    res = _eval(seeded_db, [True, False])
    assert res["all_pass"] is False
    assert res["score"] == 0.0
    assert res["n_passed"] == 1
    fails = [cr for cr in res["criteria_results"] if cr["verdict"] == "fail"]
    assert len(fails) == 1


def test_judge_call_error_captured(seeded_db: Path):
    res = _eval(seeded_db, [True, "error"])
    # the run still completes with a result for every criterion
    assert len(res["criteria_results"]) == 2
    err_crs = [cr for cr in res["criteria_results"] if "error" in cr["reasoning"]]
    assert len(err_crs) == 1
    assert res["all_pass"] is False  # the erroring criterion counts as a fail


def test_judge_model_from_fake(seeded_db: Path):
    res = _eval(seeded_db, [True, True], model_name="fake-judge")
    assert res["judge_model"] == "fake-judge"


def test_judge_model_fallback_to_env(seeded_db: Path, monkeypatch):
    monkeypatch.setenv("EVAL_MODEL", "openai/glm-5.2")
    res = _eval(seeded_db, [True, True], model_name=None)
    assert res["judge_model"] == "openai/glm-5.2"


def test_result_dict_shape(seeded_db: Path):
    res = _eval(seeded_db, [True, True])
    for key in (
        "rubric",
        "score",
        "max_score",
        "all_pass",
        "n_criteria",
        "n_passed",
        "summary",
        "criteria_results",
        "judge_model",
        "scored_at",
    ):
        assert key in res
    assert res["rubric"] == _RUBRIC
    assert res["max_score"] == 1.0
    for cr in res["criteria_results"]:
        assert set(cr.keys()) == {"id", "title", "verdict", "reasoning"}
