"""Learn node: auto-apply high-confidence clause rejections after pipeline store.

Aggregates rejection recommendations from the current run + historical runs.
When a clause accumulates enough rejections (threshold), automatically marks it
as rejected via ``bulk_review`` so it won't participate in future assembly.

Only rejects **custom** clauses; base/tagged are never touched.
"""

from __future__ import annotations

import os
from typing import Any

from src.eval.db import connect
from src.eval.pipeline_store import list_pipeline_runs, get_pipeline_run

AUTO_REJECT_THRESHOLD = int(os.environ.get("AUTO_REJECT_THRESHOLD", "3"))


def _aggregate_historical_rejections(
    contract_type: str,
    limit: int = 50,
) -> dict[int, int]:
    """Count how many times each clause_id was recommended for rejection
    across recent pipeline_runs for the same contract_type."""
    counts: dict[int, int] = {}
    runs = list_pipeline_runs(limit=limit)
    for run in runs:
        if run.get("contract_type") != contract_type:
            continue
        pr = get_pipeline_run(run["id"])
        if not pr:
            continue
        for rec in pr.get("recommendations") or []:
            if isinstance(rec, dict) and rec.get("action") == "reject":
                cid = rec.get("clause_id")
                if cid is not None:
                    counts[cid] = counts.get(cid, 0) + 1
    return counts


def _is_custom_clause(clause_id: int) -> bool:
    """Check if a clause is a custom clause (safe to reject)."""
    from src.clauses.store import get_custom_clause
    clause = get_custom_clause(clause_id)
    if not clause:
        return False
    return (clause.get("tags") or {}).get("source") == "custom"


def learn_node(state: dict) -> dict:
    """Auto-apply high-confidence clause rejections.

    Aggregates recommendations from current run + historical runs.
    Only rejects custom clauses that reach the threshold.
    """
    from src.clauses.tag_review import bulk_review

    contract_type = state["contract_type"]
    current_recs = state.get("recommendations") or []

    # Count rejections from current run
    current_counts: dict[int, int] = {}
    for r in current_recs:
        if isinstance(r, dict) and r.get("action") == "reject":
            cid = r.get("clause_id")
            if cid is not None:
                current_counts[cid] = current_counts.get(cid, 0) + 1

    # Aggregate historical rejections
    historical_counts = _aggregate_historical_rejections(contract_type, limit=50)

    # Merge counts
    all_ids = set(current_counts.keys()) | set(historical_counts.keys())
    applied: list[dict] = []

    for cid in all_ids:
        total = current_counts.get(cid, 0) + historical_counts.get(cid, 0)
        if total >= AUTO_REJECT_THRESHOLD and _is_custom_clause(cid):
            try:
                bulk_review(cid, "rejected")
                applied.append({
                    "clause_id": cid,
                    "total_count": total,
                    "current_count": current_counts.get(cid, 0),
                    "historical_count": historical_counts.get(cid, 0),
                })
            except Exception:
                pass  # fail-safe: don't crash the pipeline

    # Persist learn_applied back to the stored pipeline_run row
    pipeline_run_id = state.get("pipeline_run_id")
    if pipeline_run_id is not None:
        _update_learn_applied(pipeline_run_id, applied)

    return {"learn_applied": applied}


def _update_learn_applied(pipeline_run_id: int, applied: list[dict]) -> None:
    """Write the learn_applied JSON back to the pipeline_runs row."""
    from psycopg.types.json import Jsonb
    from src.eval.db import connect
    from src.eval.store import ensure_schema

    ensure_schema()
    conn = connect()
    try:
        conn.execute(
            "UPDATE pipeline_runs SET learn_applied = %s WHERE id = %s",
            (Jsonb(applied), pipeline_run_id),
        )
        conn.commit()
    finally:
        conn.close()
