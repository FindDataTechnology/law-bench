"""synthesize node — merge suggestions from all reviewers into one list.

Deduplicates by (section, recommendation) similarity — if two reviewers raised
the same point, the merged suggestion records both names under ``sources``
rather than appearing twice. Severity is escalated when multiple reviewers
agree (info + info -> warning, etc.).
"""
from __future__ import annotations

import time

from langchain_core.runnables import RunnableConfig

from ..state import ReviewState

_SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}


def _key(s: dict) -> tuple[str, str]:
    """A coarse dedup key: (section, first 6 chars of normalized recommendation)."""
    section = (s.get("section") or "").strip()
    rec = (s.get("recommendation") or "").strip().replace(" ", "")
    return (section, rec[:12])


def _escalate(severities: list[str]) -> str:
    """Pick the most severe among severities; tie-break to the higher rank."""
    if not severities:
        return "info"
    return max(severities, key=lambda s: _SEVERITY_RANK.get(s, 0))


def synthesize_node(state: ReviewState, config: RunnableConfig) -> dict:
    """Merge reviewer suggestions; record per-node timing."""
    t0 = time.perf_counter()
    reviews = state.get("reviews") or []

    merged: dict[tuple[str, str], dict] = {}
    for review in reviews:
        reviewer_name = review.get("name") or review.get("model")
        for s in review.get("suggestions") or []:
            k = _key(s)
            if k not in merged:
                merged[k] = {
                    "severity": s.get("severity") or "info",
                    "section": s.get("section") or "",
                    "recommendation": s.get("recommendation") or "",
                    "reason": s.get("reason") or "",
                    "sources": [reviewer_name] if reviewer_name else [],
                }
            else:
                entry = merged[k]
                entry["sources"].append(reviewer_name)
                entry["sources"] = list(dict.fromkeys(entry["sources"]))
                entry["severity"] = _escalate([
                    entry["severity"], s.get("severity") or "info"
                ])
                if s.get("reason") and not entry.get("reason"):
                    entry["reason"] = s["reason"]

    synthesized = list(merged.values())
    elapsed = time.perf_counter() - t0
    return {
        "synthesized_suggestions": synthesized,
        "current_stage": "synthesize",
        "node_timings": {**(state.get("node_timings") or {}),
                         "synthesize": round(elapsed, 3)},
    }
