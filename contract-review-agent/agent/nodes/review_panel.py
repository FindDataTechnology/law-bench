"""review_panel node — 3 reviewers in parallel, each with a different lens.

Loads reviewer configs from .env (see agent.config.reviewers()), dispatches all
three via ``asyncio.gather``, and pushes partial state to the frontend after
each reviewer completes via ``copilotkit_emit_state``.

Each reviewer's suggestions are parsed from the LLM's JSON output (best-effort:
a malformed response yields an empty suggestion list, never a crash).
"""
from __future__ import annotations

import asyncio
import json
import time

from langchain_core.runnables import RunnableConfig

from ..state import ReviewState
from .llm import call_llm
from .prompts import lens_prompt, review_user_prompt


def _parse_suggestions(text: str) -> list[dict]:
    """Best-effort parse of the reviewer's JSON response into suggestions."""
    if not text:
        return []
    try:
        data = json.loads(text)
        items = data.get("suggestions") if isinstance(data, dict) else None
        if isinstance(items, list):
            return [s for s in items if isinstance(s, dict)]
    except json.JSONDecodeError:
        # LLM may have wrapped JSON in prose; try to slice out the {...} block.
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(text[start : end + 1])
                items = data.get("suggestions") if isinstance(data, dict) else None
                if isinstance(items, list):
                    return [s for s in items if isinstance(s, dict)]
            except json.JSONDecodeError:
                pass
    return []


async def _review_once(reviewer: dict, draft: str, contract_type: str, scenario: str | None) -> dict:
    """Call one reviewer; return a ReviewResult with suggestions + metrics."""
    res = await call_llm(
        model=reviewer["model"],
        system=lens_prompt(reviewer["lens"]),
        user=review_user_prompt(draft, contract_type, scenario),
        temperature=0.0,
    )
    suggestions = _parse_suggestions(res.get("text") or "")
    return {
        "name": reviewer["name"],
        "model": reviewer["model"],
        "lens": reviewer["lens"],
        "suggestions": suggestions,
        "timing": round(res.get("latency", 0.0), 3),
        "tokens": res.get("tokens", 0),
        "error": res.get("error"),
    }


async def _emit_state(config: RunnableConfig, state: dict) -> None:
    """Best-effort state emission to the frontend.

    When running with a CopilotKit frontend, pushes partial state so the UI
    shows reviews appearing one-by-one. In a headless e2e test (no frontend),
    this is a no-op - emitting state must never break the node.
    """
    try:
        from copilotkit.langgraph import copilotkit_emit_state

        await copilotkit_emit_state(config, state)
    except Exception:
        pass


async def review_panel_node(state: ReviewState, config: RunnableConfig) -> dict:
    """Run all reviewers concurrently; stream progress after each completes."""
    reviewers = state.get("reviewers") or []
    if not reviewers:
        from ..config import reviewers as load_reviewers

        reviewers = load_reviewers()

    draft = state.get("draft_v1") or ""
    contract_type = state.get("contract_type", "")
    scenario = (state.get("tags") or {}).get("scenario")
    errors = list(state.get("errors") or [])

    t0 = time.perf_counter()
    model_calls = list(state.get("model_calls") or [])

    # Fire reviewers with configurable concurrency (default 1 = serial). The
    # relay enforces a low concurrency cap (~4 shared), so serializing the 3
    # reviewers avoids "并发请求过多" throttling. Config: REVIEW_CONCURRENCY.
    import os

    try:
        concurrency = max(1, min(int(os.environ.get("REVIEW_CONCURRENCY", "1")), len(reviewers)))
    except (TypeError, ValueError):
        concurrency = 1

    reviews: list[dict] = []
    sem = asyncio.Semaphore(concurrency)

    async def _run_one(r: dict) -> dict:
        async with sem:
            return await _review_once(r, draft, contract_type, scenario)

    coros = [_run_one(r) for r in reviewers]
    for coro, reviewer in zip(asyncio.as_completed(coros), reviewers):
        result = await coro
        reviews.append(result)
        model_calls.append({
            "model": reviewer["model"],
            "node": "review_panel",
            "tokens": result.get("tokens", 0),
            "cost": 0.0,
            "latency_seconds": result.get("timing", 0.0),
        })
        if result.get("error"):
            errors.append({"node": "review_panel", "message": result["error"]})

        # Stream partial state to the frontend after each reviewer.
        await _emit_state(config, {
            **state,
            "reviews": reviews,
            "completed_reviews": len(reviews),
            "total_reviews": len(reviewers),
            "current_stage": "review_panel",
            "model_calls": model_calls,
        })

    elapsed = time.perf_counter() - t0
    return {
        "reviews": reviews,
        "reviewers": reviewers,
        "completed_reviews": len(reviews),
        "total_reviews": len(reviewers),
        "model_calls": model_calls,
        "current_stage": "review_panel",
        "node_timings": {**(state.get("node_timings") or {}),
                         "review_panel": round(elapsed, 3)},
        "errors": errors,
    }
