"""generate_v2 node — re-assemble the contract with human-provided slot values.

Applies the human answers (slot_values) to the assembled body by replacing
every ``{{slot}}`` placeholder with its value, and (optionally) edits clause
text to reflect the accepted reviewer suggestions. Produces the final draft_v2.
"""
from __future__ import annotations

import re
import time

from langchain_core.runnables import RunnableConfig

from ..state import ReviewState

# Mirrors src.docs.slots.SLOT_PATTERN so we don't import python-docx here.
_SLOT_RE = re.compile(r"\{\{\s*([a-zA-Z_][\w-]*)\s*\}\}")


def _fill(body: str, slot_values: dict) -> str:
    """Replace every {{slot}} with its value; leave unknown slots untouched."""
    def repl(m: re.Match) -> str:
        name = m.group(1)
        return str(slot_values.get(name, m.group(0)))
    return _SLOT_RE.sub(repl, body)


async def generate_v2_node(state: ReviewState, config: RunnableConfig) -> dict:
    """Apply human slot values + accepted suggestions to produce draft_v2."""
    t0 = time.perf_counter()
    errors = list(state.get("errors") or [])

    body = state.get("draft_v1") or ""
    slot_values = state.get("slot_values") or {}
    draft_v2 = _fill(body, slot_values)

    # Accepted suggestions are recorded but not auto-applied to clause text —
    # they are surfaced in the final preview so the human can incorporate them
    # by editing the generated DOCX. Auto-rewriting clause bodies risks
    # coherence-gate failures; we leave the rewrite to the human or a future
    # improve node. This is intentional: see design.md decision 6.
    elapsed = time.perf_counter() - t0
    return {
        "draft_v2": draft_v2,
        "current_stage": "generate_v2",
        "node_timings": {**(state.get("node_timings") or {}),
                         "generate_v2": round(elapsed, 3)},
        "errors": errors,
    }
