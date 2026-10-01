"""``contract_evaluate`` / ``rubric_list`` / ``run_list`` / ``run_get`` tools.

Wraps the LLM-judge rubric evaluator in :mod:`src.eval`. ``contract_evaluate``
accepts either a file path or inline contract text, and persists the run to the
eval DB unless ``no_store`` is set.
"""

from __future__ import annotations

from pathlib import Path

import anyio

from ..server import mcp


@mcp.tool(tags={"contracts"})
async def contract_evaluate(
    contract: str,
    rubric: str,
    task: str | None = None,
    no_store: bool = False,
    verbose: bool = False,
) -> dict:
    """Evaluate a drafted contract against a named rubric (LLM-judge).

    Parameters:
        contract: path to a drafted contract file, OR inline contract text. If
            the value points at an existing file it is read; otherwise it is
            treated as the contract text itself.
        rubric: rubric name, e.g. ``"contract_drafting_v1"``.
        task: optional original user request / task description, passed to the
            judge as input context.
        no_store: when True, do not persist the run to the eval database.
        verbose: verbose judge output.

    Returns ``{rubric, judge_model, score, max_score, all_pass, n_passed,
    n_criteria, summary, criteria_results, scored_at}``. A missing rubric or
    unreadable contract raises a tool error.
    """
    from src.eval.scoring import evaluate_contract as _evaluate
    from src.eval.store import store_result

    # ponytail: file-exists check is sync + cheap; do it on the event loop
    # before hopping to the worker thread for the LLM-bound evaluation.
    path = Path(contract)
    try:
        is_file = path.is_file()
    except OSError:
        # A path-shaped but over-long / invalid string (e.g. a full inline
        # contract body) cannot be stat-ed; treat it as inline text.
        is_file = False
    if is_file:
        contract_text = path.read_text(encoding="utf-8")
        contract_path = str(path)
    else:
        contract_text = contract
        contract_path = None

    def _go() -> dict:
        result = _evaluate(
            contract_text,
            rubric,
            task_desc=task,
            verbose=verbose,
        )
        if not no_store:
            run_id = store_result(result, contract_path=contract_path, task_desc=task)
        else:
            run_id = None
        return {**result, "run_id": run_id}

    return await anyio.to_thread.run_sync(_go)


@mcp.tool(tags={"rubrics"})
async def rubric_list(include_counts: bool = False) -> list[dict]:
    """List available evaluation rubrics.

    Parameters:
        include_counts: when True, each row also carries ``id``,
            ``criterion_count``, and ``is_harbor`` (delegates to
            ``src.eval.rubric_crud.list_rubrics_with_counts``); when False
            (default), rows are ``{name, context, source}``.

    Returns the rubric rows.
    """
    if include_counts:
        from src.eval.rubric_crud import list_rubrics_with_counts

        return await anyio.to_thread.run_sync(list_rubrics_with_counts)
    from src.eval.rubric import list_rubrics as _list_rubrics

    return await anyio.to_thread.run_sync(_list_rubrics)


@mcp.tool(tags={"eval"})
async def run_list(limit: int = 20) -> list[dict]:
    """List recent evaluation runs (most recent first)."""
    from src.eval.store import list_runs as _list_runs

    return await anyio.to_thread.run_sync(_list_runs, limit)


@mcp.tool(tags={"eval"})
async def run_get(run_id: int) -> dict:
    """Fetch a single evaluation run's run-level fields and its per-criterion verdicts.

    The counterpart to ``run_list`` (which returns run-level fields only).

    Parameters:
        run_id: id of the run.

    Returns the run row (``id``, ``rubric_name``, ``contract_path``,
        ``task_desc``, ``score``, ``max_score``, ``all_pass``, ``n_criteria``,
        ``n_passed``, ``summary``, ``judge_model``, ``scored_at``,
        ``compare_run_id``, ``prompt_name``, ``prompt_type``, ``variant_label``)
        plus an ordered ``criteria_results`` list. An unknown run id raises a
        tool error.
    """
    from src.eval.store import get_run

    return await anyio.to_thread.run_sync(get_run, run_id)
