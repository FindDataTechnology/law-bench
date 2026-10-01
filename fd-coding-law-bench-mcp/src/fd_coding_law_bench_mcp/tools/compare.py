"""Compare orchestration + read tools.

Wrap :mod:`src.eval.compare` (orchestration + matrix aggregation) and the
compare/read side of :mod:`src.eval.store`. ``compare_run`` resolves prompt
**names** to records (so the caller passes names, not pre-fetched records),
then drives ``src.eval.compare.run_compare`` unchanged - drafter-only generation
plus the existing ``contract_evaluate`` judge. ``NotFoundError`` /
``ValidationError`` / ``KeyError`` surface as tool errors.
"""

from __future__ import annotations

import anyio

from ..server import mcp


@mcp.tool(tags={"eval"})
async def compare_run(
    contract_type: str,
    rubric_name: str,
    task_desc: str,
    prompt_names: list[str],
    n_drafts: int = 1,
    label: str | None = None,
    concurrency: int = 1,
) -> dict:
    """Draft + evaluate each named prompt against ``rubric_name``; persist grouped.

    For each prompt name, resolves the prompt record, generates ``n_drafts``
    drafts (drafter-only mode: one direct DRAFTER-model call per draft), judges
    each against the rubric, and persists the runs under one ``compare_runs``
    row.

    Parameters:
        contract_type: contract class key (e.g. ``"sale"``).
        rubric_name: rubric to judge each draft against.
        task_desc: the original drafting request (judge input).
        prompt_names: two or more prompt names to compare.
        n_drafts: drafts per prompt (default 1).
        label: optional label for the compare run.
        concurrency: max drafts generated simultaneously across the
            prompt x draft matrix (default 1 = sequential; clamped to
            [1, 8] by the service, effective value in the result).

    Returns the grouped compare (runs + per-criterion verdicts, no
    ``draft_text``) with ``effective_concurrency``. Fewer than two prompt
    names, an unknown rubric/prompt, or ``n_drafts < 1`` raises a tool error.
    Note: this is an expensive tool - it makes one LLM draft call per draft
    plus one judge call per draft.
    """
    from src.eval.compare import load_prompts, run_compare as _run

    def _go() -> dict:
        prompts = load_prompts(prompt_names)
        return _run(
            contract_type,
            rubric_name,
            task_desc,
            prompts,
            mode="drafter-only",
            n_drafts=n_drafts,
            label=label,
            concurrency=concurrency,
        )

    return await anyio.to_thread.run_sync(_go)


@mcp.tool(tags={"eval"})
async def compare_list(limit: int = 20) -> list[dict]:
    """List recent compare runs (compare-level fields only), newest first.

    Returns ``[{id, label, contract_type, rubric_name, task_desc, gen_mode,
    n_drafts, created_at}]``.
    """
    from src.eval.store import list_compares as _list

    return await anyio.to_thread.run_sync(_list, limit)


@mcp.tool(tags={"eval"})
async def compare_get(compare_id: int) -> dict:
    """Fetch the full grouped result for one compare.

    Parameters:
        compare_id: id of the compare run.

    Returns the ``compare_runs`` row with its ``eval_runs`` (each carrying
    per-criterion ``eval_criteria_results`` and snapshotted prompt metadata).
    ``draft_text`` is excluded - fetch it lazily via ``run_draft``. An unknown
    id raises a tool error.
    """
    from src.eval.store import get_compare as _get

    return await anyio.to_thread.run_sync(_get, compare_id)


@mcp.tool(tags={"eval"})
async def compare_matrix(compare_id: int) -> dict:
    """Fetch a compare's criteria x prompts matrix in one call.

    Equivalent to ``build_matrix(get_compare(compare_id))``. Cells are binary
    verdicts when ``n_drafts == 1`` and ``k/N`` pass-rates when ``n_drafts > 1``.

    Parameters:
        compare_id: id of the compare run.

    Returns ``{criteria, columns, cells, n_drafts}``. An unknown id raises a
    tool error.
    """
    from src.eval.compare import build_matrix
    from src.eval.store import get_compare as _get

    def _go() -> dict:
        return build_matrix(_get(compare_id))

    return await anyio.to_thread.run_sync(_go)


@mcp.tool(tags={"eval"})
async def run_draft(compare_id: int, run_id: int) -> dict:
    """Lazily fetch a single run's ``draft_text`` (verified to belong to the compare).

    Parameters:
        compare_id: id of the owning compare run.
        run_id: id of the run whose draft to fetch.

    Returns ``{run_id, prompt_name, draft_text}``. An unknown run, or a run that
    does not belong to the given compare, raises a tool error.
    """
    from src.eval.store import get_run_draft as _get

    return await anyio.to_thread.run_sync(_get, compare_id, run_id)
