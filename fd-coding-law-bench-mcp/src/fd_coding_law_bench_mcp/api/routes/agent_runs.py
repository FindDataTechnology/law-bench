"""Agent runs HTTP endpoints."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

from ..schemas import ErrorResponse


router = APIRouter()


@router.post("/agent-runs", response_model=dict, responses={400: {"model": ErrorResponse}})
async def store_agent_run(
    thread_id: str,
    contract_type: str,
    tags: Optional[Dict[str, Any]] = None,
    task_desc: Optional[str] = None,
    node_timings: Optional[Dict[str, float]] = None,
    model_calls: Optional[List[Dict[str, Any]]] = None,
    review_suggestions: Optional[List[Dict[str, Any]]] = None,
    suggestions_applied: Optional[List[Dict[str, Any]]] = None,
    total_slots: int = 0,
    human_filled_slots: int = 0,
    eval_run_id: Optional[int] = None,
    deepeval_scores: Optional[Dict[str, Any]] = None,
    total_duration: Optional[float] = None,
) -> dict:
    """Store an agent run's metrics (wrapper around MCP tool)."""
    from .server import mcp_tool_proxy

    return await mcp_tool_proxy(
        "agent_run_store",
        {
            "thread_id": thread_id,
            "contract_type": contract_type,
            "tags": tags,
            "task_desc": task_desc,
            "node_timings": node_timings,
            "model_calls": model_calls,
            "review_suggestions": review_suggestions,
            "suggestions_applied": suggestions_applied,
            "total_slots": total_slots,
            "human_filled_slots": human_filled_slots,
            "eval_run_id": eval_run_id,
            "deepeval_scores": deepeval_scores,
            "total_duration": total_duration,
        }
    )


@router.get("/agent-runs/{run_id}", response_model=dict)
async def get_agent_run(run_id: int) -> dict:
    """Get one agent run by id."""
    from .server import mcp_tool_proxy

    return await mcp_tool_proxy("agent_run_get", {"run_id": run_id})


@router.get("/agent-runs", response_model=list)
async def list_agent_runs(limit: int = 20) -> list:
    """List recent agent runs."""
    from .server import mcp_tool_proxy

    return await mcp_tool_proxy("agent_run_list", {"limit": limit})
