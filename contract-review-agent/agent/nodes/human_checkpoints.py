"""Human-in-the-loop checkpoint nodes — three LangGraph interrupt() points.

CP1 (triage_reviews):     human accepts/rejects synthesized suggestions
CP2 (fill_contract_slots): human fills EVERY slot — frontend validates full coverage
CP3 (approve_final_contract): human approves the final draft or requests changes

Each interrupt surfaces a payload the frontend renders via useHumanInTheLoop;
the value passed back via Command(resume=...) becomes the node's return value.
"""
from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from ..state import ReviewState


def human_triage_node(state: ReviewState, config: RunnableConfig) -> dict:
    """CP1: present synthesized suggestions; human picks which to apply."""
    suggestions = state.get("synthesized_suggestions") or []
    accepted: list[dict] = interrupt({
        "name": "triage_reviews",
        "suggestions": suggestions,
        "message": "请审查评审建议，选择要采纳的修改。",
    })
    # accepted may be a list of suggestion dicts, or {"accepted": [...], "rejected": [...]}
    if isinstance(accepted, dict) and isinstance(accepted.get("accepted"), list):
        accepted = accepted["accepted"]
    if not isinstance(accepted, list):
        accepted = []
    return {
        "accepted_suggestions": accepted,
        "current_stage": "human_triage",
    }


def human_quiz_node(state: ReviewState, config: RunnableConfig) -> dict:
    """CP2: present the quiz; human MUST fill every slot before resume.

    The frontend enforces full coverage (submit disabled until every required
    field has a non-empty value). We still validate server-side: any slot left
    blank is filled with its placeholder so generation v2 doesn't break.
    """
    quiz_items = state.get("quiz_items") or []
    answers: dict = interrupt({
        "name": "fill_contract_slots",
        "quiz_items": quiz_items,
        "total_slots": len(quiz_items),
        "message": "请填写所有必填字段以生成最终合同。",
    })
    slot_values = answers if isinstance(answers, dict) else {}

    # Server-side full-coverage guard: backfill blanks with placeholders.
    for item in quiz_items:
        slot = item.get("slot")
        if slot and not str(slot_values.get(slot, "")).strip():
            slot_values[slot] = item.get("example") or f"{{{{请填写{slot}}}}}"

    return {
        "slot_values": slot_values,
        "current_stage": "human_quiz",
    }


def human_review_node(state: ReviewState, config: RunnableConfig) -> dict:
    """CP3: present final draft + eval scores; human approves or requests changes."""
    payload = {
        "name": "approve_final_contract",
        "draft": state.get("draft_v2") or "",
        "eval_result": state.get("eval_result") or {},
        "deepeval_scores": state.get("deepeval_scores") or {},
        "accepted_suggestions": state.get("accepted_suggestions") or [],
        "message": "请确认最终合同。通过后导出 DOCX/PDF。",
    }
    decision = interrupt(payload)
    approval = "approved"
    if isinstance(decision, dict):
        approval = decision.get("approval") or decision.get("status") or "approved"
    elif isinstance(decision, str):
        approval = decision

    return {
        "approval": approval,
        "current_stage": "human_review",
    }
