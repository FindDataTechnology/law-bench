"""Auto-reject pipeline tool: self_heal_pipeline_run + learn node.

**Concurrency:** Safe to run in parallel (learn node is idempotent).

Same as ``self_heal_pipeline_run`` but adds a ``learn`` node after ``store`` that
auto-applies high-confidence clause rejections based on accumulated
recommendations from current and historical runs.
"""

from __future__ import annotations

import anyio

from ..server import mcp


@mcp.tool(tags={"pipeline"})
async def auto_reject_pipeline_run(
    contract_type: str,
    tags: dict | None = None,
    stance: str | None = None,
    rubric: str | None = None,
    task_desc: str | None = None,
    fill_mode: str = "llm",
    temperature: float = 0.0,
    max_iterations: int = 3,
    custom_clause_ids: list[int] | None = None,
) -> dict:
    """Generate, fill, evaluate, self-heal, then auto-apply clause rejections.

    Drives a LangGraph: ``generate -> fill -> evaluate -> check -> (improve) ->
    store -> learn``. The ``learn`` node aggregates ``clause_review``
    recommendations from the current run **and** recent historical runs; any
    **custom** clause reaching the rejection threshold
    (``AUTO_REJECT_THRESHOLD``, default 3) is automatically marked ``rejected``
    via ``bulk_review`` so it drops out of future assembly. Base/tagged clauses
    are never touched.

    Parameters:
        contract_type: contract class key (e.g. ``"sale"``).
        tags: optional ``{"scenario": ..., "stance": ...}`` (forwarded to
            ``contract_generate`` and the fill prompt).
        stance: convenience for ``tags["stance"]``.
        rubric: rubric name. If ``None``, the latest-version rubric for the type
            (highest ``contract_<type>_v<N>``) is used.
        task_desc: original drafting request (judge input context).
        fill_mode: fill strategy (currently only ``"llm"`` is implemented).
        temperature: LLM fill temperature (default ``0.0`` for reproducibility);
            recorded on the ``pipeline_runs`` row.
        max_iterations: self-heal cap (default ``3``); ``1`` disables the loop.
        custom_clause_ids: optional explicit custom-clause id list for the first
            ``generate`` (forwarded to ``contract_generate``).

    Returns ``{pipeline_run_id, eval_run_id, score, max_score, all_pass,
    n_passed, n_criteria, summary, iteration, actions_taken, recommendations,
    learn_applied}`` where ``learn_applied`` lists the clauses auto-rejected
    this run ``[{clause_id, total_count, current_count, historical_count}]``.
    An unknown contract type or a missing default rubric raises a tool error.
    """
    from ..pipeline.auto_graph import run_auto_reject_pipeline

    def _go() -> dict:
        state = run_auto_reject_pipeline(
            contract_type,
            tags=tags,
            stance=stance,
            rubric=rubric,
            task_desc=task_desc,
            fill_mode=fill_mode,
            temperature=temperature,
            max_iterations=max_iterations,
            custom_clause_ids=custom_clause_ids,
        )
        best = state.get("best") or {}
        ev = best.get("eval_result") or state.get("eval_result") or {}
        return {
            "pipeline_run_id": state.get("pipeline_run_id"),
            "eval_run_id": best.get("eval_run_id") or state.get("eval_run_id"),
            "score": ev.get("score"),
            "max_score": ev.get("max_score"),
            "all_pass": ev.get("all_pass"),
            "n_passed": ev.get("n_passed"),
            "n_criteria": ev.get("n_criteria"),
            "summary": ev.get("summary"),
            "iteration": best.get("iteration") or state.get("iteration"),
            "actions_taken": state.get("actions_taken") or [],
            "recommendations": state.get("recommendations") or [],
            "learn_applied": state.get("learn_applied") or [],
        }

    return await anyio.to_thread.run_sync(_go)
