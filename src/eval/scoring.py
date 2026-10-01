"""Evaluate a drafted contract against a rubric using deepeval's native GEval
LLM-judge, mirroring harvey-labs' all-pass rubric methodology.

harvey-labs (`evaluation/scoring.py`):
  - one LLM-judge call per criterion -> binary pass/fail verdict + reasoning
  - criteria are judged concurrently via ThreadPoolExecutor
  - task scores 1.0 ONLY if every criterion passed (all-pass); else 0.0
  - records n_criteria / n_passed diagnostics and per-criterion results

deepeval mapping (no hand-rolled prompt; uses deepeval's base GEval ability):
  - one GEval(strict_mode=True) per criterion, `criteria` = the criterion's
    guidance (== harvey-labs match_criteria). strict_mode forces binary 1/0 and
    threshold=1, so each metric's success == pass/fail verdict.
  - like harvey-labs, we call each criterion's judge directly (GEval.measure)
    in a thread pool and aggregate, rather than going through deepeval's
    evaluate() test-runner (which mis-times-out against the Ark endpoint).
  - results are read straight off the GEval instances (mutated in place).
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

from src.settings import DEFAULT_DB

from .judge import get_judge
from .rubric import load_criteria

_log = logging.getLogger(__name__)

# Judge worker bounds (design D2): the Ark relay saturates — the 429 backoff in
# _score_one is load-bearing and must survive any pool size. Ceiling 16 matches
# worst-case compare load (8 drafts + 8 judges).
_JUDGE_WORKERS_DEFAULT = 8
_JUDGE_WORKERS_CEILING = 16


def _resolve_judge_workers() -> int:
    """Resolve the default judge worker-pool size from ``EVAL_MAX_WORKERS``.

    Unset / non-integer / non-positive fall back to 8; values above 16 clamp
    to 16. Read at call time (not import time) so tests and long-running
    processes pick up changes. Fallback/clamp is logged with the effective
    value so operators see what actually ran.
    """
    raw = os.environ.get("EVAL_MAX_WORKERS")
    if raw is None or not raw.strip():
        return _JUDGE_WORKERS_DEFAULT
    try:
        value = int(raw)
    except ValueError:
        _log.warning("EVAL_MAX_WORKERS=%r is not an integer; using default %d",
                     raw, _JUDGE_WORKERS_DEFAULT)
        return _JUDGE_WORKERS_DEFAULT
    if value < 1:
        _log.warning("EVAL_MAX_WORKERS=%d is not positive; using default %d",
                     value, _JUDGE_WORKERS_DEFAULT)
        return _JUDGE_WORKERS_DEFAULT
    if value > _JUDGE_WORKERS_CEILING:
        _log.warning("EVAL_MAX_WORKERS=%d exceeds ceiling %d; clamped to %d",
                     value, _JUDGE_WORKERS_CEILING, _JUDGE_WORKERS_CEILING)
        return _JUDGE_WORKERS_CEILING
    return value


def _build_metrics(criteria: list[dict], judge, include_input: bool) -> list[GEval]:
    """One GEval per criterion, strict (binary) judging against its guidance."""
    params = [LLMTestCaseParams.ACTUAL_OUTPUT]
    if include_input:
        params.append(LLMTestCaseParams.INPUT)

    metrics: list[GEval] = []
    for c in criteria:
        metrics.append(
            GEval(
                name=c["id"],
                criteria=c["match_criteria"],
                evaluation_params=params,
                strict_mode=True,  # binary pass(1)/fail(0); threshold forced to 1
                model=judge,
                async_mode=False,  # we drive execution ourselves (sync measure)
            )
        )
    return metrics


def evaluate_contract(
    contract_text: str,
    rubric_name: str,
    task_desc: Optional[str] = None,
    judge=None,
    verbose: bool = False,
    max_workers: Optional[int] = None,
    db_path=DEFAULT_DB,
) -> dict:
    """Score a drafted contract against a named rubric; return a scores dict.

    The returned dict follows harvey-labs' scores.json shape (score, all_pass,
    n_criteria, n_passed, criteria_results, judge_model, scored_at) so output
    stays comparable to a harvey-labs run.

    ``max_workers`` left as ``None`` resolves from ``EVAL_MAX_WORKERS`` at call
    time (default 8, clamped to [1, 16]); an explicit integer takes precedence.
    ``db_path`` defaults to the project DB; tests pass a throwaway DB so they do
    not touch the development database.
    """
    if max_workers is None:
        max_workers = _resolve_judge_workers()
    criteria = load_criteria(rubric_name, db_path=db_path)  # raises KeyError / ValueError if bad
    judge = judge or get_judge()

    include_input = bool(task_desc)
    test_case = LLMTestCase(
        input=task_desc or "",
        actual_output=contract_text,
    )
    metrics = _build_metrics(criteria, judge, include_input)

    # Judge each criterion concurrently (mirrors harvey-labs' ThreadPoolExecutor).
    # Retry on rate-limit / transient relay errors: a 429 must NOT become a FAIL,
    # because a unanimous-FAIL (conf=1.0) drives the self-iteration loop to
    # generate+overwrite clauses based on noise — which is how property_service
    # collapsed to 0/10 under relay saturation. The openai SDK retries most
    # 429s already, but deepeval wraps calls and some leak through as exceptions.
    def _score_one(metric: GEval) -> None:
        for attempt in range(3):
            try:
                metric.measure(test_case, _show_indicator=False)
                return
            except Exception as e:
                s = str(e)
                if ("RateLimit" in s or "429" in s or "ServiceUnavailable" in s
                        or "503" in s) and attempt < 2:
                    time.sleep(8 * (attempt + 1))
                    continue
                metric.error = s  # one bad judge call must not sink the run
                return

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(metrics)))) as pool:
        list(pool.map(_score_one, metrics))

    criteria_results = []
    for c, g in zip(criteria, metrics):
        err = getattr(g, "error", None)
        success = bool(getattr(g, "success", False))
        criteria_results.append(
            {
                "id": c["id"],
                "title": c["title"],
                "verdict": "pass" if success else "fail",
                "reasoning": (getattr(g, "reason", "") or "")
                + (f" [error: {err}]" if err else ""),
            }
        )

    n_total = len(criteria_results)
    n_passed = sum(1 for r in criteria_results if r["verdict"] == "pass")
    all_pass = n_passed == n_total

    return {
        "rubric": rubric_name,
        "score": 1.0 if all_pass else 0.0,
        "max_score": 1.0,
        "all_pass": all_pass,
        "n_criteria": n_total,
        "n_passed": n_passed,
        "summary": (
            f"{n_passed}/{n_total} criteria passed. ALL PASS."
            if all_pass
            else f"{n_passed}/{n_total} criteria passed. Missed {n_total - n_passed} - FAIL."
        ),
        "criteria_results": criteria_results,
        "judge_model": getattr(metrics[0], "evaluation_model", None)
        or os.environ.get("EVAL_MODEL"),
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }


def evaluate_with_multi_judge(
    contract_text: str,
    rubric_name: str,
    task_desc: Optional[str] = None,
    judge_models: Optional[list[str]] = None,
    verbose: bool = False,
    max_workers: Optional[int] = None,
    db_path=DEFAULT_DB,
) -> dict:
    """Multi-judge evaluation with majority voting.

    Runs N judges in parallel (one per model), aggregates verdicts using
    majority voting. Returns consensus verdict with confidence scores.

    Args:
        contract_text: The contract to evaluate
        rubric_name: Rubric to evaluate against
        task_desc: Original user request (optional context)
        judge_models: List of model names (default: ["kimi-k3", "glm-5", "deepseek"])
        verbose: Show detailed judge output
        max_workers: Max parallel workers per judge (None -> EVAL_MAX_WORKERS)
        db_path: Database path

    Returns:
        Dict with consensus verdicts, confidence scores, and per-judge breakdown
    """
    if judge_models is None:
        judge_models = ["kimi-k3", "glm-5", "deepseek"]

    criteria = load_criteria(rubric_name, db_path=db_path)
    n_criteria = len(criteria)

    # Run each judge in parallel
    judge_results = {}
    judge_errors = []

    def _run_judge(model_name: str) -> tuple[str, dict]:
        """Run one judge model, return (model_name, result_dict)."""
        try:
            # Set EVAL_MODEL for this judge
            old_model = os.environ.get("EVAL_MODEL")
            os.environ["EVAL_MODEL"] = model_name

            result = evaluate_contract(
                contract_text=contract_text,
                rubric_name=rubric_name,
                task_desc=task_desc,
                verbose=verbose,
                max_workers=max_workers,
                db_path=db_path,
            )

            # Restore original model
            if old_model:
                os.environ["EVAL_MODEL"] = old_model

            return model_name, result
        except Exception as e:
            return model_name, {"error": str(e)}

    # Execute judges in parallel
    with ThreadPoolExecutor(max_workers=len(judge_models)) as pool:
        futures = [pool.submit(_run_judge, model) for model in judge_models]
        for future in futures:
            model_name, result = future.result()
            if "error" in result:
                judge_errors.append({"model": model_name, "error": result["error"]})
            else:
                judge_results[model_name] = result

    n_judges = len(judge_results)
    if n_judges == 0:
        raise RuntimeError(f"All judges failed: {judge_errors}")

    # Aggregate verdicts per criterion using majority voting
    consensus_results = []
    n_unanimous_pass = 0
    n_majority_pass = 0
    n_failures = 0

    for i, criterion in enumerate(criteria):
        criterion_id = criterion["id"]

        # Collect verdicts from all judges
        verdicts = []
        per_judge_reasoning = {}
        for model_name, result in judge_results.items():
            if "criteria_results" in result and i < len(result["criteria_results"]):
                cr = result["criteria_results"][i]
                verdicts.append(cr["verdict"])
                per_judge_reasoning[model_name] = cr.get("reasoning", "")

        # Majority vote
        pass_count = verdicts.count("pass")
        fail_count = verdicts.count("fail")

        if pass_count > fail_count:
            consensus_verdict = "pass"
            confidence = pass_count / n_judges
            if pass_count == n_judges:
                n_unanimous_pass += 1
            else:
                n_majority_pass += 1
        else:
            consensus_verdict = "fail"
            confidence = fail_count / n_judges
            n_failures += 1

        # Use reasoning from first judge that agreed with consensus
        consensus_reasoning = ""
        for model_name, result in judge_results.items():
            if "criteria_results" in result and i < len(result["criteria_results"]):
                cr = result["criteria_results"][i]
                if cr["verdict"] == consensus_verdict:
                    consensus_reasoning = cr.get("reasoning", "")
                    break

        consensus_results.append({
            "id": criterion_id,
            "title": criterion["title"],
            "verdict": consensus_verdict,
            "confidence": confidence,
            "reasoning": consensus_reasoning,
            "per_judge_reasoning": per_judge_reasoning,
        })

    n_passed = n_unanimous_pass + n_majority_pass
    all_pass = n_passed == n_criteria

    # Determine low_confidence flag
    min_confidence = min((r["confidence"] for r in consensus_results), default=0.0)
    low_confidence = min_confidence < 0.67 if n_judges < 3 else False

    return {
        "rubric": rubric_name,
        "score": 1.0 if all_pass and not low_confidence else 0.0,
        "max_score": 1.0,
        "all_pass": all_pass,
        "n_criteria": n_criteria,
        "n_passed": n_passed,
        "n_unanimous_pass": n_unanimous_pass,
        "n_majority_pass": n_majority_pass,
        "n_failures": n_failures,
        "low_confidence": low_confidence,
        "summary": (
            f"{n_passed}/{n_criteria} criteria passed. ALL PASS."
            if all_pass
            else f"{n_passed}/{n_criteria} criteria passed. Missed {n_criteria - n_passed} - FAIL."
        ),
        "criteria_results": consensus_results,
        "judge_models": list(judge_results.keys()),
        "judge_errors": judge_errors,
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }
