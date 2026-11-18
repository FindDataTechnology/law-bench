"""LangGraph StateGraph for the contract-review-agent.

Graph topology:
  START
  → generate_v1          (assemble draft + extract slots)
  → review_panel         (3 reviewers in parallel, stream state)
  → synthesize           (merge suggestions)
  → human_triage         🚦 CP1: interrupt, human accepts/rejects
  → generate_quiz        (LLM generates question per slot)
  → human_quiz           🚦 CP2: interrupt, human fills ALL slots
  → generate_v2          (apply slot values to draft)
  → evaluate             (rubric + deepeval dual eval)
  → human_review         🚦 CP3: interrupt, human approves final
  → export               (DOCX/PDF)
  → END

Compiled with AsyncPostgresSaver checkpointer so interrupt() can pause/resume
across HTTP requests.
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from .state import ReviewState


def build_review_graph(checkpointer: Any = None) -> Any:
    """Compile and return the review-agent StateGraph.

    Pass an initialized checkpointer (e.g. AsyncPostgresSaver) when calling
    from a context that already has one. When ``checkpointer`` is None, this
    lazily initializes the shared AsyncPostgresSaver via get_checkpointer()
    (only safe outside a running event loop; inside a loop, pass one in).
    """
    from agent.nodes.evaluate import evaluate_node
    from agent.nodes.export import export_node
    from agent.nodes.generate_quiz import generate_quiz_node
    from agent.nodes.generate_v1 import generate_v1_node
    from agent.nodes.generate_v2 import generate_v2_node
    from agent.nodes.human_checkpoints import (
        human_quiz_node,
        human_review_node,
        human_triage_node,
    )
    from agent.nodes.metrics import metrics_node
    from agent.nodes.review_panel import review_panel_node
    from agent.nodes.synthesize import synthesize_node

    g = StateGraph(ReviewState)

    # Nodes
    g.add_node("generate_v1", generate_v1_node)
    g.add_node("review_panel", review_panel_node)
    g.add_node("synthesize", synthesize_node)
    g.add_node("human_triage", human_triage_node)
    g.add_node("generate_quiz", generate_quiz_node)
    g.add_node("human_quiz", human_quiz_node)
    g.add_node("generate_v2", generate_v2_node)
    g.add_node("evaluate", evaluate_node)
    g.add_node("human_review", human_review_node)
    g.add_node("export", export_node)
    g.add_node("metrics", metrics_node)

    # Edges
    g.add_edge(START, "generate_v1")
    g.add_edge("generate_v1", "review_panel")
    g.add_edge("review_panel", "synthesize")
    g.add_edge("synthesize", "human_triage")
    g.add_edge("human_triage", "generate_quiz")
    g.add_edge("generate_quiz", "human_quiz")
    g.add_edge("human_quiz", "generate_v2")
    g.add_edge("generate_v2", "evaluate")
    g.add_edge("evaluate", "human_review")
    g.add_edge("human_review", "export")
    g.add_edge("export", "metrics")
    g.add_edge("metrics", END)

    # If no checkpointer was passed, lazily get one (only works outside a
    # running event loop). interrupt() requires a checkpointer.
    if checkpointer is None:
        import asyncio

        from .checkpointer import get_checkpointer

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                checkpointer = None
            else:
                checkpointer = loop.run_until_complete(get_checkpointer())
        except RuntimeError:
            checkpointer = asyncio.run(get_checkpointer())

    return g.compile(checkpointer=checkpointer)
