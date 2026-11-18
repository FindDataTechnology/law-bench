"""CopilotKit AG-UI integration - mount the LangGraph graph as an HTTP endpoint.

The frontend's CopilotKit provider talks to this endpoint via the AG-UI protocol.
LangGraph's interrupt() checkpoints are bridged to the frontend's
useHumanInTheLoop hook, enabling the three human-in-the-loop checkpoints.
"""
from __future__ import annotations

from fastapi import FastAPI


def setup_copilotkit(app: FastAPI) -> None:
    """Mount the review-agent graph at the root path for CopilotKit."""
    try:
        from ag_ui_langgraph import add_langgraph_fastapi_endpoint
        from copilotkit import LangGraphAGUIAgent
    except ImportError as e:
        raise ImportError(
            "CopilotKit dependencies not installed. Run: pip install copilotkit ag-ui-langgraph"
        ) from e

    from agent.graph import build_review_graph

    # Build the graph with MemorySaver. We can't init the AsyncPostgresSaver
    # here (this runs at import time, before the event loop / lifespan starts),
    # and MemorySaver is sufficient for a single-replica deployment - interrupt
    # state lives in-process for the duration of an agent run. Switch to
    # PostgresSaver later for multi-replica durability.
    from langgraph.checkpoint.memory import MemorySaver

    graph = build_review_graph(checkpointer=MemorySaver())

    # Wrap as a CopilotKit-compatible agent. LangGraphAGUIAgent already handles
    # the copilotkit state schema; no extra middleware needed on the endpoint.
    agent = LangGraphAGUIAgent(
        name="contract-review-agent",
        description="Multi-model contract review with human checkpoints",
        graph=graph,
    )

    # Add the AG-UI endpoint at / (POST) + /health (GET).
    add_langgraph_fastapi_endpoint(
        app=app,
        agent=agent,
        path="/",
    )
