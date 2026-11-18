"""HTTP routes for agent_runs metrics — store / get / list."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


router = APIRouter()


# --- Request / Response schemas ---

class AgentRunStoreRequest(BaseModel):
    thread_id: str
    contract_type: str
    tags: dict = Field(default_factory=dict)
    task_desc: str | None = None
    node_timings: dict = Field(default_factory=dict)
    model_calls: list[dict] = Field(default_factory=list)
    review_suggestions: list[dict] = Field(default_factory=list)
    suggestions_applied: list[dict] = Field(default_factory=list)
    total_slots: int = 0
    human_filled_slots: int = 0
    eval_run_id: int | None = None
    deepeval_scores: dict = Field(default_factory=dict)
    total_duration: float | None = None


class AgentRunResponse(BaseModel):
    id: int
    thread_id: str
    contract_type: str
    tags: dict
    task_desc: str | None
    node_timings: dict
    model_calls: list[dict]
    review_suggestions: list[dict]
    suggestions_applied: list[dict]
    total_slots: int
    human_filled_slots: int
    eval_run_id: int | None
    deepeval_scores: dict
    total_duration: float | None
    created_at: str


class AgentRunListResponse(BaseModel):
    id: int
    thread_id: str
    contract_type: str
    task_desc: str | None
    total_slots: int
    human_filled_slots: int
    eval_run_id: int | None
    total_duration: float | None
    created_at: str


# --- Routes ---

@router.post("/agent-runs", response_model=dict)
async def store_agent_run(req: AgentRunStoreRequest) -> dict:
    """Insert one agent_runs row; return {id: run_id}."""
    from agent.store import insert_agent_run

    try:
        run_id = insert_agent_run(req.model_dump())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"id": run_id}


@router.get("/agent-runs/{run_id}", response_model=AgentRunResponse)
async def get_agent_run(run_id: int) -> Any:
    """One agent_runs row (full), or 404."""
    from agent.store import get_agent_run

    row = get_agent_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"agent run {run_id} not found")
    ca = row.get("created_at")
    if ca is not None and not isinstance(ca, str):
        row["created_at"] = ca.isoformat() if hasattr(ca, "isoformat") else str(ca)
    return row


@router.get("/agent-runs", response_model=list[AgentRunListResponse])
async def list_agent_runs(limit: int = 20) -> list[dict]:
    """Recent agent_runs rows (summary fields only)."""
    from agent.store import list_agent_runs

    rows = list_agent_runs(limit=limit)
    # Convert datetime -> ISO string for the response model.
    for r in rows:
        ca = r.get("created_at")
        if ca is not None and not isinstance(ca, str):
            r["created_at"] = ca.isoformat() if hasattr(ca, "isoformat") else str(ca)
    return rows
