"""Auto-reject pipeline: extends the self-heal pipeline with a learn node.

**Concurrency:** Safe to run in parallel (learn node is idempotent).

Graph structure:
  START → generate → fill → evaluate → check → [improve → generate]* → store → learn → END

The learn node automatically applies high-confidence clause rejections based on
accumulated recommendations from current and historical runs.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .graph import (
    PipelineState,
    build_self_heal_graph,
    check_node,
    evaluate_node,
    fill_node,
    generate_node,
    improve_node,
    store_node,
    _route,
    default_rubric,
)
from .learn import learn_node


def build_auto_reject_graph():
    """Compile and return the auto-reject pipeline StateGraph.

    Same as build_self_heal_graph() but adds a learn node after store.
    """
    g = StateGraph(PipelineState)
    g.add_node("generate", generate_node)
    g.add_node("fill", fill_node)
    g.add_node("evaluate", evaluate_node)
    g.add_node("check", check_node)
    g.add_node("improve", improve_node)
    g.add_node("store", store_node)
    g.add_node("learn", learn_node)

    g.add_edge(START, "generate")
    g.add_edge("generate", "fill")
    g.add_edge("fill", "evaluate")
    g.add_edge("evaluate", "check")
    g.add_conditional_edges("check", _route, {"store": "store", "improve": "improve"})
    g.add_edge("improve", "generate")
    g.add_edge("store", "learn")
    g.add_edge("learn", END)

    return g.compile()


def run_auto_reject_pipeline(
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
    """Run the auto-reject pipeline; return final state with learn_applied."""
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
        "learn_applied": [],
    }
    return build_auto_reject_graph().invoke(initial)


# Backward compatibility aliases (deprecated)
build_auto_graph = build_auto_reject_graph
run_auto_pipeline = run_auto_reject_pipeline
