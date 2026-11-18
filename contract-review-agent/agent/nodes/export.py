"""export node - generate DOCX/PDF artifact via src.clauses.assemble directly.

Uses ``generate_contract_assembled`` (the same assembler generate_v1 uses) with
``format="both"`` to render the final contract as DOCX + PDF. Returns the file
paths so the frontend can offer downloads.
"""
from __future__ import annotations

import time

from langchain_core.runnables import RunnableConfig

from ..state import ReviewState


async def export_node(state: ReviewState, config: RunnableConfig) -> dict:
    """Generate final DOCX/PDF; record paths in state."""
    t0 = time.perf_counter()
    errors = list(state.get("errors") or [])

    try:
        import anyio

        from src.clauses.assemble import generate_contract_assembled

        def _do_export():
            return generate_contract_assembled(
                state["contract_type"],
                scenario=(state.get("tags") or {}).get("scenario"),
                stance=(state.get("tags") or {}).get("stance"),
                format="both",
            )

        res = await anyio.to_thread.run_sync(_do_export)
        paths = {
            "docx_path": res.get("docx_path"),
            "pdf_path": res.get("pdf_path"),
        }
    except Exception as exc:  # noqa: BLE001
        paths = {"error": str(exc)}
        errors.append({"node": "export", "message": str(exc)})

    elapsed = time.perf_counter() - t0
    return {
        "export_paths": paths,
        "current_stage": "export",
        "node_timings": {**(state.get("node_timings") or {}),
                         "export": round(elapsed, 3)},
        "errors": errors,
    }
