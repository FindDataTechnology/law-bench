"""Tag iteration pipeline: self-heal + suggest retag.

**Concurrency:** Safe to run in parallel (read-only on clauses table).

Graph structure:
  START → generate → fill → evaluate → check → [improve → generate]* → store → suggest_retag → END

This pipeline extends the self-heal pipeline with a suggest_retag node that
analyzes failing clauses and suggests tag modifications for human review.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .graph import (
    PipelineState,
    check_node,
    evaluate_node,
    fill_node,
    generate_node,
    improve_node,
    store_node,
    _route,
    default_rubric,
)
from .suggest_retag import suggest_retag_node


def build_tag_iteration_graph():
    """Compile and return the tag iteration pipeline StateGraph."""
    g = StateGraph(PipelineState)
    g.add_node("generate", generate_node)
    g.add_node("fill", fill_node)
    g.add_node("evaluate", evaluate_node)
    g.add_node("check", check_node)
    g.add_node("improve", improve_node)
    g.add_node("store", store_node)
    g.add_node("suggest_retag", suggest_retag_node)

    g.add_edge(START, "generate")
    g.add_edge("generate", "fill")
    g.add_edge("fill", "evaluate")
    g.add_edge("evaluate", "check")
    g.add_conditional_edges("check", _route, {"store": "store", "improve": "improve"})
    g.add_edge("improve", "generate")
    g.add_edge("store", "suggest_retag")
    g.add_edge("suggest_retag", END)

    return g.compile()


def run_tag_iteration_pipeline(
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
    """Run the tag iteration pipeline; return final state with retag_suggestions."""
    if rubric is None:
        rubric = default_rubric(contract_type)
    if stance is None:
        stance = (tags or {}).get("stance")

    initial: dict = {
        "contract_type": contract_type,
        "tags": tags or {},
        "stance": stance,
        "rubric": rubric,
        "task_desc": task_desc,
        "fill_mode": fill_mode,
        "temperature": temperature,
        "max_iterations": max_iterations,
        "custom_clause_ids": custom_clause_ids,
        "iteration": 1,
        "excluded_ids": [],
        "actions_taken": [],
        "recommendations": [],
        "retag_suggestions": [],
    }
    return build_tag_iteration_graph().invoke(initial)
