"""Contract pipeline tools: LangGraph generate -> fill -> evaluate -> self-heal -> store.

``pipeline_run`` runs the graph (see :mod:`..pipeline.graph`) and persists one
``pipeline_runs`` row linking to the ``eval_runs`` row produced by
``contract_evaluate``. ``pipeline_list`` / ``pipeline_get`` read it back. Mirrors
the ``compare_run`` / ``compare_list`` / ``compare_get`` shape.
"""

from __future__ import annotations

import anyio

from ..server import mcp


@mcp.tool(tags={"pipeline"})
async def self_heal_pipeline_run(
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
    """Generate, fill, evaluate, and self-heal a contract in one pipeline run.

    Drives a LangGraph: ``generate -> fill -> evaluate -> check -> (improve) ->
    store``. The ``improve`` node excludes thin custom clauses **per run** (via
    ``custom_clause_ids``) and records ``clause_review`` recommendations without
    executing them. The best-scoring iteration is persisted.

    **Concurrency:** Safe to run in parallel (read-only on clauses table).

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
    n_passed, n_criteria, summary, iteration, actions_taken, recommendations}``.
    An unknown contract type or a missing default rubric raises a tool error.
    """
    from ..pipeline.graph import run_self_heal_pipeline

    def _go() -> dict:
        state = run_self_heal_pipeline(
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
        }

    return await anyio.to_thread.run_sync(_go)


# Backward compatibility alias (deprecated)
pipeline_run = self_heal_pipeline_run


@mcp.tool(tags={"pipeline"})
async def pipeline_list(limit: int = 20) -> list[dict]:
    """List recent pipeline runs (most recent first).

    Returns ``[{id, contract_type, stance, rubric_name, task_desc, score,
    max_score, n_passed, n_criteria, all_pass, iteration, eval_run_id,
    fill_temperature, created_at}]``.
    """
    from src.eval.pipeline_store import list_pipeline_runs

    return await anyio.to_thread.run_sync(list_pipeline_runs, limit)


@mcp.tool(tags={"pipeline"})
async def pipeline_get(pipeline_id: int) -> dict:
    """Fetch one pipeline run + its linked eval run's per-criterion verdicts.

    Parameters:
        pipeline_id: id of the pipeline run.

    Returns the ``pipeline_runs`` row (incl. ``filled_text``, ``fill_values``,
    ``actions_taken``, ``recommendations``, ``fill_temperature``) plus the
    ordered ``criteria_results`` from the linked ``eval_runs`` row. An unknown id
    raises a tool error.
    """
    from src.eval.errors import NotFoundError
    from src.eval.pipeline_store import get_pipeline_run
    from src.eval.store import get_run

    # ponytail: wrap the multi-call sequence in a single run_sync so we take
    # one thread hop for the whole read, not one per DB query.
    def _go() -> dict:
        row = get_pipeline_run(pipeline_id)
        if row is None:
            raise NotFoundError(f"pipeline run not found: {pipeline_id}")
        out = dict(row)
        if out.get("all_pass") is not None:
            out["all_pass"] = bool(out["all_pass"])
        eval_run_id = out.get("eval_run_id")
        if eval_run_id:
            try:
                out["criteria_results"] = get_run(eval_run_id).get("criteria_results")
            except Exception:  # noqa: BLE001 - eval run missing -> None, don't fail the read
                out["criteria_results"] = None
        else:
            out["criteria_results"] = None
        return out

    return await anyio.to_thread.run_sync(_go)
