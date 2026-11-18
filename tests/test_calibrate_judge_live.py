"""Tests for the live judge calibration driver's vote-share confidence channel
(change add-judge-model-selection, tasks 2.1-2.3).

Covers ``scripts/calibrate_judge_live.py``: k-sample aggregation (majority
vote share, partial/all-failed discipline), the k=1 no-channel legacy path,
CLI validation, sampling-temperature wiring, and the run_calibration kwargs
assembly — all with mocked judge/calls, no network and no DB.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import calibrate_judge_live as driver  # noqa: E402


PAIR = {
    "pair_id": 42,
    "criterion_id": "unit_price",
    "guidance": "must state a unit price",
    "draft_text": "contract text",
    "human_pass": True,
    "judge_pass": None,
}


def _attempt(verdict: bool, error=None, confidence=0.9) -> dict:
    return {
        "pair_id": PAIR["pair_id"],
        "criterion_id": PAIR["criterion_id"],
        "judge_verdict": verdict,
        "human_verdict": True,
        "confidence": confidence,
        "legacy_judge_verdict": None,
        "reasoning": "some reasoning CONFIDENCE: 0.90",
        "call_error": error,
    }


class FakeConn:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeJudge:
    def __init__(self):
        self.temperature = 0.0
        self.verdicts = []
        self.calls = 0

    def make_attempt(self, pair):
        i = self.calls
        self.calls += 1
        verdict = self.verdicts[i % len(self.verdicts)]
        return _attempt(verdict)


class TestAggregate:
    def test_five_votes_majority_share(self):
        attempts = [_attempt(True), _attempt(True), _attempt(True),
                    _attempt(False), _attempt(False)]
        rec = driver._aggregate(PAIR, attempts, samples=5)
        assert rec["judge_verdict"] is True
        assert rec["confidence"] == pytest.approx(0.6)
        assert rec["confidence_source"] == "vote_share"
        assert rec["votes"] == [True, True, True, False, False]
        assert rec["dropped"] is False
        assert rec["n_sample_errors"] == 0

    def test_all_failed_item_is_dropped_not_a_fake_fail(self):
        attempts = [_attempt(False, error="429") for _ in range(5)]
        rec = driver._aggregate(PAIR, attempts, samples=5)
        assert rec["dropped"] is True
        assert rec["judge_verdict"] is False
        assert rec["confidence"] is None
        assert rec["confidence_source"] == "none"
        assert rec["n_sample_errors"] == 5
        assert len(rec["sample_errors"]) == 5

    def test_partial_failure_keeps_successful_votes_and_denominator(self):
        attempts = [_attempt(True), _attempt(True), _attempt(False),
                    _attempt(False), _attempt(False, error="503")]
        rec = driver._aggregate(PAIR, attempts, samples=5)
        assert rec["votes"] == [True, True, False, False]
        assert rec["judge_verdict"] is False  # 2-2 tie -> conservative fail
        assert rec["confidence"] == pytest.approx(0.5)
        assert rec["confidence_source"] == "vote_share"
        assert rec["n_sample_errors"] == 1
        assert rec["dropped"] is False

    def test_k1_uses_legacy_parse_and_marks_no_channel(self):
        rec = driver._aggregate(PAIR, [_attempt(True)], samples=1)
        assert rec["judge_verdict"] is True
        assert rec["confidence"] == 0.9
        assert rec["confidence_source"] == "none"

    def test_score_pair_runs_k_independent_attempts(self, monkeypatch):
        monkeypatch.setattr(driver, "_score_pair_once", lambda p, j: _attempt(True))
        rec = driver._score_pair(PAIR, object(), samples=5)
        assert len(rec["votes"]) == 5
        assert rec["confidence"] == 1.0

    def test_evaluation_steps_cached_per_criteria(self, monkeypatch):
        driver._STEPS_CACHE.clear()
        calls = []

        class FakeMetric:
            def __init__(self, **kw):
                self.criteria = kw["criteria"]

            def _generate_evaluation_steps(self, multimodal):
                calls.append(self.criteria)
                return ["step-a", "step-b"]

        monkeypatch.setattr(driver, "GEval", FakeMetric)
        steps_a = driver._evaluation_steps_for("criterion A", object())
        steps_b = driver._evaluation_steps_for("criterion A", object())
        driver._evaluation_steps_for("criterion B", object())
        assert steps_a == steps_b == ["step-a", "step-b"]
        assert calls == ["criterion A", "criterion B"]

    def test_step_probe_failure_falls_back_without_caching(self, monkeypatch):
        driver._STEPS_CACHE.clear()

        class BadMetric:
            def __init__(self, **kw):
                pass

            def _generate_evaluation_steps(self, multimodal):
                raise TimeoutError("relay stalled")

        monkeypatch.setattr(driver, "GEval", BadMetric)
        assert driver._evaluation_steps_for("criterion B", object()) is None
        assert "criterion B" not in driver._STEPS_CACHE

    def test_unhandled_call_exception_is_a_dropped_item(self, monkeypatch):
        def boom(pair, judge):
            raise RuntimeError("relay exploded")

        monkeypatch.setattr(driver, "_score_pair_once", boom)
        rec = driver._score_pair(PAIR, object(), samples=5)
        assert rec["dropped"] is True
        assert rec["n_sample_errors"] == 5
        assert rec["confidence"] is None
        assert rec["confidence_source"] == "none"


class TestCLI:
    def test_even_samples_rejected(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "argv", ["calibrate_judge_live.py", "--gold",
                                         str(tmp_path / "g.json"), "--samples", "4"])
        with pytest.raises(SystemExit) as exc:
            driver.main()
        assert exc.value.code == 2

    def test_zero_samples_rejected(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "argv", ["calibrate_judge_live.py", "--gold",
                                         str(tmp_path / "g.json"), "--samples", "0"])
        with pytest.raises(SystemExit) as exc:
            driver.main()
        assert exc.value.code == 2

    def test_temperature_only_set_when_sampling(self, monkeypatch, tmp_path):
        gold = tmp_path / "g.json"
        gold.write_text(json.dumps([PAIR]))
        judge = FakeJudge()
        judge.verdicts = [True]
        captured = {}

        monkeypatch.setattr(sys, "argv", ["calibrate_judge_live.py", "--gold",
                                         str(gold), "--samples", "5",
                                         "--workers", "1", "--out",
                                         str(tmp_path / "out.json")])
        monkeypatch.setattr(driver, "get_judge", lambda: judge)
        monkeypatch.setattr(driver, "_score_pair_once", lambda p, j: judge.make_attempt(p))
        monkeypatch.setattr(driver, "connect", lambda: FakeConn())
        monkeypatch.setattr(driver, "run_calibration",
                            lambda conn, **kw: (captured.update(kw), {"run_id": 7,
                                "agree_rate": 1.0, "balanced_accuracy": 1.0,
                                "kappa": 1.0, "all_pass": True, "n": 1})[1])
        monkeypatch.setattr(driver, "load_dotenv", lambda: None)
        assert driver.main() == 0
        assert judge.temperature == pytest.approx(0.7)
        assert captured["samples"] == 5
        assert captured["n_calls"] == 5
        assert captured["candidate"]
        assert captured["gold_records"][0]["confidence_source"] == "vote_share"
        assert captured["gold_records"][0]["confidence"] == 1.0

    def test_k1_leaves_temperature_untouched(self, monkeypatch, tmp_path):
        gold = tmp_path / "g.json"
        gold.write_text(json.dumps([PAIR]))
        judge = FakeJudge()
        judge.verdicts = [True]
        captured = {}
        monkeypatch.setattr(sys, "argv", ["calibrate_judge_live.py", "--gold",
                                         str(gold), "--samples", "1",
                                         "--workers", "1", "--out",
                                         str(tmp_path / "out.json")])
        monkeypatch.setattr(driver, "get_judge", lambda: judge)
        monkeypatch.setattr(driver, "_score_pair_once", lambda p, j: judge.make_attempt(p))
        monkeypatch.setattr(driver, "connect", lambda: FakeConn())
        monkeypatch.setattr(driver, "run_calibration",
                            lambda conn, **kw: (captured.update(kw), {"run_id": 8,
                                "agree_rate": 1.0, "balanced_accuracy": 1.0,
                                "kappa": 1.0, "all_pass": False, "n": 1})[1])
        monkeypatch.setattr(driver, "load_dotenv", lambda: None)
        assert driver.main() == 0
        assert judge.temperature == 0.0
        assert captured["samples"] == 1
        assert captured["gold_records"][0]["confidence_source"] == "none"

    def test_all_items_dropped_stores_nothing(self, monkeypatch, tmp_path):
        gold = tmp_path / "g.json"
        gold.write_text(json.dumps([PAIR]))
        monkeypatch.setattr(sys, "argv", ["calibrate_judge_live.py", "--gold",
                                         str(gold), "--samples", "5",
                                         "--workers", "1", "--out",
                                         str(tmp_path / "out.json")])
        monkeypatch.setattr(driver, "get_judge", lambda: FakeJudge())
        monkeypatch.setattr(driver, "_score_pair_once",
                            lambda p, j: _attempt(False, error="429"))
        monkeypatch.setattr(driver, "load_dotenv", lambda: None)
        called = []
        monkeypatch.setattr(driver, "run_calibration",
                            lambda *a, **kw: called.append(kw))
        assert driver.main() == 1
        assert not called
        out = json.loads((tmp_path / "out.json").read_text())
        assert out[0]["dropped"] is True


class TestSamplingTemperature:
    def test_env_override_and_guard(self, monkeypatch):
        monkeypatch.setenv("JUDGE_SAMPLING_TEMPERATURE", "1.2")
        assert driver._sampling_temperature() == 1.2
        monkeypatch.setenv("JUDGE_SAMPLING_TEMPERATURE", "0")
        with pytest.raises(ValueError, match="in \\(0, 2\\]"):
            driver._sampling_temperature()
        monkeypatch.setenv("JUDGE_SAMPLING_TEMPERATURE", "banana")
        with pytest.raises(ValueError, match="must be a number"):
            driver._sampling_temperature()
