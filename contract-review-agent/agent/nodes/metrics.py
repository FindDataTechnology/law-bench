"""metrics node — aggregate timings + model calls, persist to agent_runs.

After all nodes complete, this one computes total_duration, counts human_filled
slots, aggregates node_timings / model_calls / slot coverage, and inserts a row
into agent_runs via store.insert_agent_run(). The returned run_id links back to
this agent run for querying later.
"""
from __future__ import annotations

import asyncio
import time

from langchain_core.runnables import RunnableConfig

from ..state import ReviewState
from ..store import insert_agent_run


def _aggregate_metrics(state: ReviewState) -> dict:
    """Compute total_duration and slot coverage (sync wrapper)."""
    node_timings = state.get("node_timings") or {}
    elapsed = sum(node_timings.values()) if node_timings else 0.0

    slots = state.get("slots") or []
    slot_values = state.get("slot_values") or {}
    filled = sum(1 for s in slots if str(slot_values.get(s, "")).strip())

    return {
        "total_duration": round(elapsed, 3),
        "total_slots": len(slots),
        "human_filled_slots": filled,
    }


async def metrics_node(state: ReviewState, config: RunnableConfig) -> dict:
    """Persist metrics to agent_runs; return run_id."""
    t0 = time.perf_counter()
    errors = list(state.get("errors") or [])
    thread_id = state.get("thread_id", f"thread_{int(t0 * 1000)}")

    agg = _aggregate_metrics(state)

    row = {
        "thread_id": thread_id,
        "contract_type": state.get("contract_type", ""),
        "tags": state.get("tags") or {},
        "task_desc": state.get("task_desc"),
        "node_timings": state.get("node_timings") or {},
        "model_calls": state.get("model_calls") or [],
        "review_suggestions": state.get("synthesized_suggestions") or [],
        "suggestions_applied": state.get("accepted_suggestions") or [],
        "total_slots": agg["total_slots"],
        "human_filled_slots": agg["human_filled_slots"],
        "eval_run_id": state.get("eval_run_id"),
        "deepeval_scores": state.get("deepeval_scores") or {},
        "total_duration": agg["total_duration"],
    }

    try:
        loop = asyncio.get_event_loop()
        run_id = await loop.run_in_executor(None, insert_agent_run, row)
    except Exception as exc:  # noqa: BLE001
        errors.append({"node": "metrics", "message": f"insert_agent_run failed: {exc}"})
        run_id = None

    elapsed = time.perf_counter() - t0
    return {
        "run_id": run_id,
        "current_stage": "complete",
        "metrics_elapsed": round(elapsed, 3),
        "errors": errors,
    }
