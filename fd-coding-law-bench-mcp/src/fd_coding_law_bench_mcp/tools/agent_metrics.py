"""Agent metrics tools — CRUD for agent_runs table.

These tools expose the ``agent_runs`` table (per-run metrics for the review-agent)
via MCP so any client can query agent performance: per-node timing, model call
breakdown (tokens/cost), review suggestions, slot coverage stats.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from ..annotations import annotations_for
from ..server import mcp

# Make the law-template repo importable so `from agent.store` resolves.
_AGENT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))


@mcp.tool(tags={"metrics"}, annotations=annotations_for("agent_run_store"))
def agent_run_store(
    thread_id: str,
    contract_type: str,
    tags: dict | None = None,
    task_desc: str | None = None,
    node_timings: dict | None = None,
    model_calls: list[dict] | None = None,
    review_suggestions: list[dict] | None = None,
    suggestions_applied: list[dict] | None = None,
    total_slots: int = 0,
    human_filled_slots: int = 0,
    eval_run_id: int | None = None,
    deepeval_scores: dict | None = None,
    total_duration: float | None = None,
) -> int:
    """Store an agent run's metrics into the ``agent_runs`` table.

    This is called by the review-agent at the end of a run to persist all
    instrumentation data: timing, token usage, reviewer suggestions, slot
    coverage, evaluation linkage.

    Parameters:
        thread_id: LangGraph thread identifier.
        contract_type: e.g. "sale" or "lease".
        tags: {scenario, stance} used for generation.
        task_desc: optional drafting request text.
        node_timings: {node_name: seconds}.
        model_calls: [{model, node, tokens, cost, latency_seconds}].
        review_suggestions: full synthesized suggestions (pre-triage).
        suggestions_applied: which suggestions the human accepted.
        total_slots: number of slots in the contract.
        human_filled_slots: how many the human filled.
        eval_run_id: FK to eval_runs if rubric eval was run.
        deepeval_scores: {hallucination, faithfulness, slot_relevance}.
        total_duration: wall-clock seconds from START to END.

    Returns the new row id. Raises ValueError on missing required fields.
    """
    from agent.store import insert_agent_run

    row = {
        "thread_id": thread_id,
        "contract_type": contract_type,
        "tags": tags or {},
        "task_desc": task_desc,
        "node_timings": node_timings or {},
        "model_calls": model_calls or [],
        "review_suggestions": review_suggestions or [],
        "suggestions_applied": suggestions_applied or [],
        "total_slots": total_slots,
        "human_filled_slots": human_filled_slots,
        "eval_run_id": eval_run_id,
        "deepeval_scores": deepeval_scores or {},
        "total_duration": total_duration,
    }
    return insert_agent_run(row)


@mcp.tool(tags={"metrics"}, annotations=annotations_for("agent_run_get"))
def agent_run_get(run_id: int) -> dict | None:
    """Get one ``agent_runs`` row (full) by id.

    Returns ``{...}`` with all columns, or ``None`` if absent.
    """
    from agent.store import get_agent_run

    return get_agent_run(run_id)


@mcp.tool(tags={"metrics", "query"}, annotations=annotations_for("agent_run_list"))
def agent_run_list(limit: int = 20) -> list[dict]:
    """List recent ``agent_runs`` rows (summary fields only).

    Returns ``[{id, thread_id, contract_type, task_desc, total_slots,
    human_filled_slots, eval_run_id, total_duration, created_at}]``.
    """
    from agent.store import list_agent_runs

    return list_agent_runs(limit=limit)

# ── 长任务句柄查询（mcp-long-running-operations 组 5）────────────────────


@mcp.tool(tags={"metrics", "query"}, annotations=annotations_for("task_status"))
def task_status(handle: str) -> dict:
    """按任务句柄查状态与结果（统一了 pipeline 与 batch 两个家族）。

    `self_heal_pipeline_run` 返回 `pipeline_run_id`（数字），
    `contract_generate_batch` 返回 `trace_id`（`trace-` 前缀）。此前调用方
    拿到一个 id 要自己知道该去哪张表查——一个没有查询路径的句柄等于没有句柄。

    Returns ``{handle, kind, found, status, progress, counts, result?, error?}``。

    **状态如实**：pipeline 家族跑完即落库，故库里查到就是 completed、查不到
    就是 not_found；batch 家族的 trace_id 只是日志关联键、不落条目表，故
    报 `unknown_not_persisted` 并说明"逐条结果只在调用返回里"。这里刻意不
    编造 running/interrupted——那会让调用方对着一个假的进度条干等。
    """
    from ..tasks import task_status as _impl

    return _impl(handle)


@mcp.tool(tags={"metrics", "query"}, annotations=annotations_for("task_failed_items"))
def task_failed_items(handle: str) -> list[str]:
    """取某任务的失败/未完成条目，供分项重试。

    pipeline 家族在全通过时返回空列表；未全通过时返回一条说明（含 iteration，
    调用方据此判断是否要换 rubric 重跑而不是重跑同一条）。batch 家族无法从
    句柄反推条目，返回空列表——请按 `task_status` 的 error 说明处理。
    """
    from ..tasks import failed_items_for

    return failed_items_for(handle)
