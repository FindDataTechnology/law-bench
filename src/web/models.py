"""Pydantic request models for the evaluation-rules web API."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class CriterionIn(BaseModel):
    """A criterion submitted as part of a rubric create/update payload."""

    name: str
    description: str
    guidance: str


class RubricCreate(BaseModel):
    name: str
    context: str
    description: Optional[str] = None
    criteria: list[CriterionIn] = Field(default_factory=list)


class RubricUpdate(BaseModel):
    name: str
    context: str
    description: Optional[str] = None


class CriterionCreate(BaseModel):
    name: str
    description: str
    guidance: str


class CriterionUpdate(BaseModel):
    name: str
    description: str
    guidance: str


class ReorderRequest(BaseModel):
    ordered_criterion_ids: list[int]


class PromptCreate(BaseModel):
    """Payload to create a generation prompt."""

    name: str
    contract_type: str
    purpose: str
    content: str
    description: Optional[str] = None
    prompt_type: Optional[str] = None


class PromptUpdate(BaseModel):
    """Payload to update a generation prompt (full record)."""

    name: str
    contract_type: str
    purpose: str
    content: str
    description: Optional[str] = None
    prompt_type: Optional[str] = None


class CompareCreate(BaseModel):
    """Payload to create and run a prompt compare."""

    contract_type: str
    rubric_name: str
    task_desc: str
    prompts: list[str]
    mode: str = "drafter-only"
    n_drafts: int = 1
    # Max drafts generated simultaneously (handler clamps to [1, 8]; the
    # service layer owns the bound).
    concurrency: int = Field(default=1, ge=1)
    label: Optional[str] = None


class EvaluateSubmitResponse(BaseModel):
    """Response from POST /api/evaluate (202 Accepted)."""

    run_id: int
    status: str


class EvaluateRunSummary(BaseModel):
    """Summary row for GET /api/evaluate (list)."""

    id: int
    rubric_name: str
    status: str
    score: Optional[float] = None
    all_pass: Optional[bool] = None
    n_passed: Optional[int] = None
    n_criteria: Optional[int] = None
    error_message: Optional[str] = None
    judge_model: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None


class EvaluateRunDetail(BaseModel):
    """Full detail for GET /api/evaluate/{run_id}."""

    id: int
    rubric_name: str
    status: str
    contract_text: str
    score: Optional[float] = None
    all_pass: Optional[bool] = None
    n_passed: Optional[int] = None
    n_criteria: Optional[int] = None
    results: Optional[dict] = None
    error_message: Optional[str] = None
    judge_model: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None


# --- contract generation modes -------------------------------------------- #


class GenerationRequest(BaseModel):
    """Shared payload for the generation-mode routes (D/E/F/G).

    Mirrors the existing ``GenerateRequest`` (mode B/C) plus an optional
    ``mode`` field the panel sends for bookkeeping; the route validates the
    mode against its own. ``tag_combinations`` is only used by mode D.
    """

    mode: Optional[str] = None
    stance: Optional[str] = None
    scenario: Optional[str] = None
    custom_clause_ids: Optional[list[int]] = None
    format: str = "docx"
    tag_combinations: Optional[list[dict]] = None
    enumerate_all: bool = False
    max_concurrent: int = 5
    rubric: Optional[str] = None
    task_desc: Optional[str] = None
    max_iterations: int = 3
    temperature: float = 0.0


class GenerationJobSubmit(BaseModel):
    """Response from async generation routes (202 Accepted)."""

    job_id: int
    status: str


class GenerationJobDetail(BaseModel):
    """Full row for GET /api/generation-jobs/{id}."""

    id: int
    kind: str
    contract_type: str
    status: str
    result_ref: Optional[Any] = None
    error_message: Optional[str] = None
    created_at: str
    updated_at: str


# --- API-key management (auth) --------------------------------------------- #


class ApiKeyCreate(BaseModel):
    """Payload to create an API key (POST /api/keys)."""

    label: str
    scopes: list[str] = Field(default_factory=list)


class ApiKeyCreated(BaseModel):
    """Response from POST /api/keys — the plaintext is shown ONCE."""

    key: str
    label: str
    scopes: list[str] = Field(default_factory=list)


class ApiKeyOut(BaseModel):
    """A listed API key row (never the hash, never the plaintext)."""

    id: int
    key_prefix: str
    label: str
    scopes: list[str] = Field(default_factory=list)
    created_at: str
    last_used_at: Optional[str] = None
    revoked_at: Optional[str] = None
