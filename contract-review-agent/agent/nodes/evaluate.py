"""evaluate node — dual evaluation: existing rubric eval + deepeval metrics.

Rubric side: reuse ``src.eval.scoring.evaluate_contract`` (criterion PASS/FAIL
via deepeval GEval judge pointed at the Ark endpoint). The result includes a
run_id persisted to eval_runs.

Deepeval side: run three metrics directly:
- HallucinationMetric: did the fill invent terms not in the assembled body?
- FaithfulnessMetric: is draft_v2 faithful to the clause instructions?
- GEval("Slot Relevance"): are filled slot values contextually appropriate?

Both run concurrently via anyio; the node never crashes on a metric error.

Config (env):
- EVAL_MAX_WORKERS: max concurrent criterion judges (default 2; lower to avoid
  API rate limits, raise for speed when the endpoint allows it).
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from dotenv import load_dotenv
from langchain_core.runnables import RunnableConfig

from ..state import ReviewState

load_dotenv()


def _eval_max_workers() -> int:
    """Read EVAL_MAX_WORKERS from env, clamped to [1, 16]. Default 2."""
    try:
        val = int(os.environ.get("EVAL_MAX_WORKERS", "2"))
    except (TypeError, ValueError):
        return 2
    return max(1, min(16, val))


def _run_rubric_eval(state: ReviewState) -> dict:
    """Run the existing rubric eval; returns the scores dict (or {error})."""
    from src.eval.scoring import evaluate_contract

    contract_type = state.get("contract_type", "")
    try:
        from .rubric_name import default_rubric
        rubric = default_rubric(contract_type)
    except Exception:
        rubric = None
    if not rubric:
        # fall back to any contract_<type>_v<N> name if our resolver missed it.
        try:
            from src.eval.rubric import list_rubrics
            names = [r["name"] for r in list_rubrics()]
            matches = [n for n in names if n.startswith(f"contract_{contract_type}_")]
            matches.sort()
            rubric = matches[-1] if matches else None
        except Exception:
            rubric = None
    if not rubric:
        return {"error": f"no rubric found for contract type {contract_type!r}"}

    try:
        result = evaluate_contract(
            contract_text=state.get("draft_v2") or "",
            rubric_name=rubric,
            task_desc=state.get("task_desc"),
            max_workers=_eval_max_workers(),  # configurable to avoid rate limits
        )
        result["run_id"] = result.get("run_id")  # may be None if no_store
        return result
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


async def _run_deepeval_metrics(state: ReviewState) -> dict:
    """Run hallucination + faithfulness + slot-relevance; never raises."""
    from deepeval.metrics import HallucinationMetric, FaithfulnessMetric, GEval
    from deepeval.test_case import LLMTestCase, LLMTestCaseParams
    from src.eval.judge import get_judge

    draft_v2 = state.get("draft_v2") or ""
    instructions = state.get("instructions") or []
    context = [str(i.get("description") or "") for i in instructions]
    scores: dict[str, Any] = {}

    try:
        judge = get_judge()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"judge init failed: {exc}"}

    test_case = LLMTestCase(
        input=state.get("task_desc") or state.get("contract_type") or "",
        actual_output=draft_v2,
        context=context,
    )

    # HallucinationMetric expects retrieval_context for "no hallucination" verdicts.
    try:
        test_case.retrieval_context = context
    except Exception:
        pass

    async def _measure(name: str, metric: Any) -> None:
        try:
            metric.measure(test_case, _show_indicator=False)
            scores[name] = {
                "score": float(getattr(metric, "score", 0.0) or 0.0),
                "success": bool(getattr(metric, "is_successful", lambda: False)()),
                "reason": getattr(metric, "reason", "") or "",
            }
        except Exception as exc:  # noqa: BLE001
            scores[name] = {"error": str(exc)}

    await asyncio.gather(
        _measure("hallucination", HallucinationMetric(threshold=0.5, model=judge)),
        _measure("faithfulness", FaithfulnessMetric(threshold=0.5, model=judge)),
        _measure(
            "slot_relevance",
            GEval(
                name="Slot Relevance",
                criteria=(
                    "判断合同中填充的槽位值（如当事人名称、标的、金额、日期）"
                    "是否与合同类型和场景一致、是否真实合理。"
                ),
                evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT],
                threshold=0.5,
                model=judge,
            ),
        ),
    )
    return scores


async def evaluate_node(state: ReviewState, config: RunnableConfig) -> dict:
    """Run rubric + deepeval concurrently; persist rubric result."""
    t0 = time.perf_counter()
    errors = list(state.get("errors") or [])

    # Rubric eval is sync + thread-bound (uses ThreadPoolExecutor internally);
    # run it in a worker thread so it doesn't block the event loop.
    loop = asyncio.get_event_loop()
    rubric_result = await loop.run_in_executor(None, _run_rubric_eval, state)
    if "error" in rubric_result:
        errors.append({"node": "evaluate", "message": f"rubric: {rubric_result['error']}"})

    deepeval_scores = await _run_deepeval_metrics(state)
    if isinstance(deepeval_scores, dict) and "error" in deepeval_scores:
        errors.append({"node": "evaluate", "message": f"deepeval: {deepeval_scores['error']}"})

    eval_run_id = None
    if isinstance(rubric_result, dict):
        eval_run_id = rubric_result.get("run_id")

    elapsed = time.perf_counter() - t0
    return {
        "eval_result": rubric_result,
        "eval_run_id": eval_run_id,
        "deepeval_scores": deepeval_scores,
        "current_stage": "evaluate",
        "node_timings": {**(state.get("node_timings") or {}),
                         "evaluate": round(elapsed, 3)},
        "errors": errors,
    }
