"""Tests for judge worker-pool resolution and the rate-limit backoff invariant.

Covers the ``EVAL_MAX_WORKERS`` resolver (pure env function), how the resolved
value flows into the judge thread pool, explicit-arg precedence, and the 429
backoff that must fire regardless of pool size (design D1/D2; the
``evaluation-concurrency`` spec).

Hermetic: resolver tests are env-only; flow tests spy on ``ThreadPoolExecutor``
in the scoring module; the backoff test replaces ``_build_metrics`` with fake
metrics and stubs ``time.sleep`` so no real waiting happens.
"""

from __future__ import annotations

import src.eval.scoring as scoring
from _fakes import FakeJudge
from src.eval.scoring import _resolve_judge_workers, evaluate_contract

_RUBRIC = "l_rubric"  # seeded with criteria c1, c2 (pool caps at len(metrics))


# --- resolver: EVAL_MAX_WORKERS parsing ------------------------------------- #


def test_resolver_unset_defaults_to_8(monkeypatch):
    monkeypatch.delenv("EVAL_MAX_WORKERS", raising=False)
    assert _resolve_judge_workers() == 8


def test_resolver_valid_value(monkeypatch):
    monkeypatch.setenv("EVAL_MAX_WORKERS", "12")
    assert _resolve_judge_workers() == 12


def test_resolver_clamps_to_ceiling(monkeypatch):
    monkeypatch.setenv("EVAL_MAX_WORKERS", "64")
    assert _resolve_judge_workers() == 16


def test_resolver_invalid_falls_back_to_8(monkeypatch):
    monkeypatch.setenv("EVAL_MAX_WORKERS", "abc")
    assert _resolve_judge_workers() == 8


def test_resolver_non_positive_falls_back_to_8(monkeypatch):
    monkeypatch.setenv("EVAL_MAX_WORKERS", "0")
    assert _resolve_judge_workers() == 8
    monkeypatch.setenv("EVAL_MAX_WORKERS", "-3")
    assert _resolve_judge_workers() == 8


def test_resolver_blank_falls_back_to_8(monkeypatch):
    monkeypatch.setenv("EVAL_MAX_WORKERS", "   ")
    assert _resolve_judge_workers() == 8


# --- resolution flows into the judge pool ----------------------------------- #


class _PoolRecorder:
    """Patches scoring's ThreadPoolExecutor with a subclass recording sizes."""

    def __init__(self, monkeypatch):
        self.sizes: list[int] = []
        real = scoring.ThreadPoolExecutor
        outer = self

        class _Recording(real):
            def __init__(self, max_workers=None, **kw):
                outer.sizes.append(max_workers)
                super().__init__(max_workers=max_workers, **kw)

        monkeypatch.setattr(scoring, "ThreadPoolExecutor", _Recording)


def _run(judge, db, **kw) -> dict:
    return evaluate_contract("合同正文", _RUBRIC, judge=judge, db_path=db, **kw)


def test_unset_env_flows_default_into_pool(seeded_db, monkeypatch):
    monkeypatch.delenv("EVAL_MAX_WORKERS", raising=False)
    rec = _PoolRecorder(monkeypatch)
    _run(FakeJudge(verdicts=[True, True]), seeded_db)
    # default 8 capped by the rubric's 2 criteria -> 2 (not 1: an unclamped
    # env of 1 would give 1, proving the 8 default reached the pool)
    assert rec.sizes == [2]


def test_env_override_flows_into_pool(seeded_db, monkeypatch):
    monkeypatch.setenv("EVAL_MAX_WORKERS", "1")
    rec = _PoolRecorder(monkeypatch)
    _run(FakeJudge(verdicts=[True, True]), seeded_db)
    assert rec.sizes == [1]


def test_explicit_max_workers_beats_env(seeded_db, monkeypatch):
    monkeypatch.setenv("EVAL_MAX_WORKERS", "12")
    rec = _PoolRecorder(monkeypatch)
    _run(FakeJudge(verdicts=[True, True]), seeded_db, max_workers=1)
    # explicit 1, not min(12, 2)=2: the explicit arg must win
    assert rec.sizes == [1]


# --- backoff invariant under elevated concurrency --------------------------- #


class _FakeMetric:
    """Metric double honoring the contract scoring reads (see tests/_fakes.py).

    ``script`` is the ordered per-call outcome list: ``"429"`` raises a
    rate-limit error, ``"boom"`` a non-retryable error, ``"ok"`` passes.
    Outcomes beyond the script length repeat the last entry.
    """

    def __init__(self, name: str, script: list[str]):
        self.name = name
        self.script = list(script)
        self.measure_calls = 0
        self.success = False
        self.reason = ""
        self.error = None
        self.evaluation_model = "fake"

    def measure(self, test_case, _show_indicator=False):
        self.measure_calls += 1
        outcome = self.script[min(self.measure_calls - 1, len(self.script) - 1)]
        if outcome == "429":
            raise RuntimeError("RateLimitError: 429 too many requests for model")
        if outcome == "boom":
            raise RuntimeError("connection reset by peer")
        self.success = True
        self.reason = "fake pass"


def _with_fake_metrics(monkeypatch, metrics):
    monkeypatch.setattr(scoring, "_build_metrics", lambda *a, **k: list(metrics))


def test_rate_limit_retries_then_passes_under_elevated_pool(seeded_db, monkeypatch):
    """Two 429s then success must still PASS at elevated concurrency."""
    monkeypatch.setenv("EVAL_MAX_WORKERS", "16")  # elevated: pool = min(16, 2) = 2
    sleeps: list[int] = []
    monkeypatch.setattr(scoring.time, "sleep", lambda s: sleeps.append(s))
    m1 = _FakeMetric("c1", ["429", "429", "ok"])
    m2 = _FakeMetric("c2", ["ok"])
    _with_fake_metrics(monkeypatch, [m1, m2])

    # judge is inert (metrics are fakes) but must be injected so the real
    # get_judge() env check never runs.
    res = _run(judge=FakeJudge(verdicts=[True, True]), db=seeded_db)

    assert m1.measure_calls == 3  # retried twice, then scored
    assert sleeps == [8, 16]  # escalating backoff fired
    assert res["criteria_results"][0]["verdict"] == "pass"  # 429 != FAIL
    assert res["all_pass"] is True


def test_exhausted_retries_mark_only_their_own_criterion(seeded_db, monkeypatch):
    monkeypatch.setenv("EVAL_MAX_WORKERS", "16")
    sleeps: list[int] = []
    monkeypatch.setattr(scoring.time, "sleep", lambda s: sleeps.append(s))
    m1 = _FakeMetric("c1", ["429", "429", "429"])  # never succeeds
    m2 = _FakeMetric("c2", ["ok"])
    _with_fake_metrics(monkeypatch, [m1, m2])

    res = _run(judge=FakeJudge(verdicts=[True, True]), db=seeded_db)

    assert m1.measure_calls == 3  # 3 attempts, no 4th
    assert sleeps == [8, 16]  # no sleep after the final failed attempt
    assert res["n_passed"] == 1
    failed = [cr for cr in res["criteria_results"] if cr["verdict"] == "fail"]
    assert len(failed) == 1
    assert "error" in failed[0]["reasoning"]  # error surfaced on that criterion
    assert res["criteria_results"][1]["verdict"] == "pass"  # sibling unaffected


def test_non_retryable_error_marks_only_their_own_criterion(seeded_db, monkeypatch):
    monkeypatch.setenv("EVAL_MAX_WORKERS", "16")
    monkeypatch.setattr(scoring.time, "sleep", lambda s: None)
    m1 = _FakeMetric("c1", ["boom"])  # non-rate-limit: no retry
    m2 = _FakeMetric("c2", ["ok"])
    _with_fake_metrics(monkeypatch, [m1, m2])

    res = _run(judge=FakeJudge(verdicts=[True, True]), db=seeded_db)

    assert m1.measure_calls == 1  # connection error did not retry
    assert res["n_passed"] == 1
    assert "error" in res["criteria_results"][0]["reasoning"]
