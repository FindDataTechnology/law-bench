"""Tag iteration pipeline tools: suggest and apply tag changes.

``tag_iteration_suggest`` runs the tag iteration pipeline and returns suggestions
for tag modifications based on LLM analysis of failing clauses.

``tag_iteration_apply`` applies approved tag changes with rollback protection.
Uses pg_advisory_lock to prevent concurrent modifications.

**Concurrency:**
- ``tag_iteration_suggest``: Safe to run in parallel (read-only)
- ``tag_iteration_apply``: Must be serialized (uses advisory lock)
"""

from __future__ import annotations

import anyio

from ..server import mcp


@mcp.tool(tags={"pipeline"})
async def tag_iteration_suggest(
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
    """Analyze failing clauses and suggest tag modifications.

    Drives a LangGraph: ``generate -> fill -> evaluate -> check -> (improve) ->
    store -> suggest_retag``. The ``suggest_retag`` node uses LLM to analyze
    clauses that caused evaluation failures and suggests tag modifications
    (scenario, stance, strength, etc.) that might improve future evaluations.

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
        temperature: LLM fill temperature (default ``0.0`` for reproducibility).
        max_iterations: self-heal cap (default ``3``); ``1`` disables the loop.
        custom_clause_ids: optional explicit custom-clause id list for the first
            ``generate`` (forwarded to ``contract_generate``).

    Returns ``{pipeline_run_id, eval_run_id, score, max_score, all_pass,
    n_passed, n_criteria, summary, iteration, retag_suggestions}`` where
    ``retag_suggestions`` is a list of ``{clause_id, section, current_tags,
    suggested_tags, reason}`` for human review.

    Use ``tag_iteration_apply`` to apply approved suggestions.
    """
    from ..pipeline.tag_iteration_graph import run_tag_iteration_pipeline

    def _go() -> dict:
        state = run_tag_iteration_pipeline(
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
            "retag_suggestions": state.get("retag_suggestions") or [],
        }

    return await anyio.to_thread.run_sync(_go)


@mcp.tool(tags={"pipeline"})
async def tag_iteration_apply(
    approved_suggestions: list[dict],
    contract_type: str,
    tags: dict | None = None,
    stance: str | None = None,
    rubric: str | None = None,
    task_desc: str | None = None,
) -> dict:
    """Apply approved tag changes with rollback protection.

    Takes a list of approved suggestions from ``tag_iteration_suggest`` and
    applies the tag modifications. Then re-evaluates the contract to verify
    the changes improved the score. If the score decreased, automatically
    rolls back to the original tags.

    **Concurrency:** Uses pg_advisory_lock to prevent concurrent modifications.
    Only one ``tag_iteration_apply`` can run at a time.

    Parameters:
        approved_suggestions: list of ``{clause_id, suggested_tags}`` from
            ``tag_iteration_suggest`` output. Only ``clause_id`` and
            ``suggested_tags`` are used; other fields are ignored.
        contract_type: contract class key (e.g. ``"sale"``).
        tags: optional ``{"scenario": ..., "stance": ...}`` for re-evaluation.
        stance: convenience for ``tags["stance"]``.
        rubric: rubric name. If ``None``, uses latest-version rubric.
        task_desc: original drafting request for re-evaluation context.

    Returns ``{applied: [{clause_id, original_tags, new_tags}], rolled_back: bool,
    score_before: float, score_after: float, error: str | None}``.
    If ``rolled_back`` is true, all changes were reverted due to score decrease.
    """
    from src.clauses.store import get_custom_clause, update_clause
    from src.eval.db import connect
    from ..pipeline.graph import run_self_heal_pipeline

    def _go() -> dict:
        # Acquire advisory lock (serialized access)
        conn = connect()
        try:
            conn.execute("SET lock_timeout = '30s'")
            conn.execute("SELECT pg_advisory_lock(hashtext('tag_iteration'))")

            try:
                # Save original tags and apply new tags
                applied = []
                original_tags_map = {}

                for s in approved_suggestions:
                    clause_id = s.get("clause_id")
                    new_tags = s.get("suggested_tags")
                    if clause_id is None or not isinstance(new_tags, dict):
                        continue

                    # Get current clause
                    clause = get_custom_clause(clause_id)
                    if not clause:
                        continue

                    # Save original tags
                    original_tags = clause.get("tags") or {}
                    original_tags_map[clause_id] = original_tags

                    # Merge new tags with existing (preserve unspecified dims)
                    merged_tags = {**original_tags, **new_tags}

                    # Apply new tags
                    update_clause(clause_id, {"tags": merged_tags})
                    applied.append({
                        "clause_id": clause_id,
                        "original_tags": original_tags,
                        "new_tags": merged_tags,
                    })

                if not applied:
                    return {
                        "applied": [],
                        "rolled_back": False,
                        "score_before": 0.0,
                        "score_after": 0.0,
                        "error": "No valid suggestions to apply",
                    }

                # Re-evaluate with new tags
                # First, get the score before (from the original pipeline run)
                # We'll run a fresh evaluation to get score_before
                state_before = run_self_heal_pipeline(
                    contract_type,
                    tags=tags,
                    stance=stance,
                    rubric=rubric,
                    task_desc=task_desc,
                    max_iterations=1,  # No self-heal, just evaluate
                )
                score_before = (state_before.get("eval_result") or {}).get("score", 0.0)

                # Now evaluate with new tags (already applied)
                state_after = run_self_heal_pipeline(
                    contract_type,
                    tags=tags,
                    stance=stance,
                    rubric=rubric,
                    task_desc=task_desc,
                    max_iterations=1,
                )
                score_after = (state_after.get("eval_result") or {}).get("score", 0.0)

                # Check if score decreased
                rolled_back = False
                if score_after < score_before:
                    # Rollback: restore original tags
                    for clause_id, original_tags in original_tags_map.items():
                        update_clause(clause_id, {"tags": original_tags})
                    rolled_back = True

                return {
                    "applied": applied,
                    "rolled_back": rolled_back,
                    "score_before": score_before,
                    "score_after": score_after,
                    "error": None,
                }

            finally:
                # Release advisory lock
                conn.execute("SELECT pg_advisory_unlock(hashtext('tag_iteration'))")
                conn.commit()
        finally:
            conn.close()

    return await anyio.to_thread.run_sync(_go)
