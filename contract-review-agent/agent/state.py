"""ReviewState — the LangGraph state schema for the contract-review-agent.

One TypedDict carries every field the nodes read/write, so CopilotKit can sync
the whole state to the frontend in one shot. All fields are optional
(``total=False``) so nodes only return the keys they actually mutated.
"""
from __future__ import annotations

from typing import TypedDict


class ReviewerConfig(TypedDict):
    name: str
    model: str
    lens: str  # legal_accuracy | commercial_fairness | completeness


class ReviewResult(TypedDict, total=False):
    name: str
    model: str
    lens: str
    suggestions: list[dict]      # [{severity, section, recommendation, reason}]
    timing: float                 # seconds this reviewer took
    tokens: int
    error: str | None


class Suggestion(TypedDict, total=False):
    severity: str                # critical | warning | info
    section: str
    recommendation: str
    reason: str
    sources: list[str]           # reviewer names that raised it


class QuizItem(TypedDict, total=False):
    slot: str
    question: str
    required: bool
    label: str
    description: str
    example: str


class ModelCall(TypedDict, total=False):
    model: str
    node: str
    tokens: int
    cost: float
    latency_seconds: float


class ReviewState(TypedDict, total=False):
    # --- input ---
    contract_type: str
    tags: dict                    # {scenario, stance, ...}
    task_desc: str | None
    thread_id: str

    # --- generation v1 ---
    draft_v1: str
    slots: list[str]
    instructions: list[dict]
    law_refs: list[dict]

    # --- review panel ---
    reviewers: list[ReviewerConfig]
    reviews: list[ReviewResult]
    completed_reviews: int
    total_reviews: int

    # --- synthesis + triage (CP1) ---
    synthesized_suggestions: list[Suggestion]
    accepted_suggestions: list[Suggestion]

    # --- quiz (CP2) ---
    quiz_items: list[QuizItem]
    slot_values: dict             # {slot_name: value}

    # --- generation v2 ---
    draft_v2: str

    # --- evaluation ---
    eval_result: dict             # rubric eval (criterion PASS/FAIL)
    eval_run_id: int | None
    deepeval_scores: dict         # {hallucination, faithfulness, slot_relevance}

    # --- approval (CP3) ---
    approval: str | None          # "approved" | "changes_requested"
    export_path: str | None

    # --- metrics ---
    node_timings: dict            # {node_name: seconds}
    model_calls: list[ModelCall]
    total_duration: float
    current_stage: str           # for frontend progress display

    # --- errors ---
    errors: list[dict]            # [{node, message}]
