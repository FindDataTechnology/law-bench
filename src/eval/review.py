"""Human-review tasks over eval verdicts (change add-web-human-review).

One ``review_tasks`` row is one *annotation slot* on one ``eval_criteria_results``
row within a batch. Double annotation is two slot rows (``slot`` 1..N), not two
columns — see design.md D3. Rows stay unclaimed (``annotator`` NULL) until a
decision lands, and the decision is a conditional ``UPDATE ... WHERE
status='pending'`` so exactly one of two concurrent annotators wins (D4).

Two batch types drive two forms:

- ``validity``     — blind: the decision page must not expose the model verdict
                     or reasoning while the row is pending, so the annotator's
                     own verdict is independent (D2).
- ``gold_curation``— verification: the model verdict and reasoning are shown and
                     the annotator approves/rejects/skips.

The ``annotator`` stamp always comes from the authenticated session; this module
never reads it from request input.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from .db import connect
from .errors import NotFoundError
from .store import DEFAULT_DB, ensure_schema

BATCH_TYPES = ("validity", "gold_curation")
VALIDITY_VERDICTS = ("pass", "fail")
CURATION_VERDICTS = ("approved", "rejected", "skipped")

_RUBRIC_RE = re.compile(r"^contract_(?P<type>.+?)_v\d+$")


def contract_type_from_rubric(rubric_name: str | None) -> str | None:
    """``contract_lease_v3`` -> ``lease``; anything else -> None."""
    if not rubric_name:
        return None
    m = _RUBRIC_RE.match(rubric_name)
    return m.group("type") if m else None


def _verdicts_for(batch_type: str) -> tuple[str, ...]:
    return VALIDITY_VERDICTS if batch_type == "validity" else CURATION_VERDICTS


def create_batch(
    *,
    batch_id: str,
    batch_type: str,
    eval_criteria_result_ids: list[int],
    annotators: int = 1,
    db: Any = DEFAULT_DB,
) -> dict:
    """Create ``annotators`` slots per source row. Idempotent per batch_id.

    Returns ``{"batch_id", "batch_type", "created", "existing", "total"}`` —
    re-running with the same batch_id creates nothing and reports what was
    already there, so a sampling script can be re-run safely.
    """
    if batch_type not in BATCH_TYPES:
        raise ValueError(f"unknown batch_type: {batch_type!r}")
    if annotators < 1:
        raise ValueError("annotators must be >= 1")
    if not eval_criteria_result_ids:
        raise ValueError("no eval_criteria_result_ids given")
    ensure_schema(db)
    conn = connect(db)
    try:
        created = 0
        for result_id in eval_criteria_result_ids:
            for slot in range(1, annotators + 1):
                cur = conn.execute(
                    "INSERT INTO review_tasks "
                    "(batch_id, batch_type, eval_criteria_result_id, slot) "
                    "VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (batch_id, eval_criteria_result_id, slot) DO NOTHING",
                    (batch_id, batch_type, result_id, slot),
                )
                created += cur.rowcount or 0
        conn.commit()
        cur = conn.execute(
            "SELECT count(*) AS n FROM review_tasks WHERE batch_id = %s", (batch_id,)
        )
        total = cur.fetchone()["n"]
        return {
            "batch_id": batch_id,
            "batch_type": batch_type,
            "created": created,
            "existing": total - created,
            "total": total,
        }
    finally:
        conn.close()


def list_batches(db: Any = DEFAULT_DB) -> list[dict]:
    """One row per batch: type, size, decided/pending counts, annotators seen."""
    ensure_schema(db)
    conn = connect(db)
    try:
        cur = conn.execute(
            "SELECT batch_id, "
            "       min(batch_type) AS batch_type, "
            "       count(*) AS total, "
            "       count(*) FILTER (WHERE status = 'decided') AS decided, "
            "       count(*) FILTER (WHERE status = 'pending') AS pending, "
            "       count(DISTINCT annotator) AS annotators, "
            "       min(created_at) AS created_at "
            "FROM review_tasks "
            "GROUP BY batch_id "
            "ORDER BY min(created_at) DESC"
        )
        return cur.fetchall()
    finally:
        conn.close()


def batch_stats(batch_id: str, db: Any = DEFAULT_DB) -> dict:
    """Per-annotator decision counts inside one batch."""
    ensure_schema(db)
    conn = connect(db)
    try:
        cur = conn.execute(
            "SELECT annotator, count(*) AS decided, "
            "       count(*) FILTER (WHERE annotator_verdict IN ('pass','approved')) AS positive "
            "FROM review_tasks "
            "WHERE batch_id = %s AND status = 'decided' "
            "GROUP BY annotator ORDER BY annotator",
            (batch_id,),
        )
        return {"batch_id": batch_id, "by_annotator": cur.fetchall()}
    finally:
        conn.close()


def list_tasks(
    *,
    batch_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 200,
    for_annotator: Optional[str] = None,
    db: Any = DEFAULT_DB,
) -> list[dict]:
    """Task queue rows with just enough context for the list page.

    ``for_annotator`` additionally hides items that annotator has already decided
    in the same batch: with multi-slot items, every slot of an item looks like a
    separate pending row, and letting one person claim both would defeat the
    independence that double annotation exists for.
    """
    ensure_schema(db)
    where, params = [], []
    if batch_id:
        where.append("t.batch_id = %s")
        params.append(batch_id)
    if status:
        where.append("t.status = %s")
        params.append(status)
    if for_annotator:
        where.append(
            "NOT EXISTS (SELECT 1 FROM review_tasks t2 "
            "            WHERE t2.batch_id = t.batch_id "
            "              AND t2.eval_criteria_result_id = t.eval_criteria_result_id "
            "              AND t2.annotator = %s AND t2.status = 'decided')"
        )
        params.append(for_annotator)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    conn = connect(db)
    try:
        cur = conn.execute(
            "SELECT t.id, t.batch_id, t.batch_type, t.slot, t.status, "
            "       t.annotator, t.annotator_verdict, t.reviewed_at, "
            "       r.criterion_id, r.title AS criterion_title, r.ordinal, "
            "       e.rubric_name, e.scored_at "
            "FROM review_tasks t "
            "JOIN eval_criteria_results r ON r.id = t.eval_criteria_result_id "
            "JOIN eval_runs e ON e.id = r.run_id "
            f"{clause} "
            "ORDER BY t.batch_id, e.scored_at, r.ordinal, t.slot "
            "LIMIT %s",
            tuple(params),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    for row in rows:
        row["contract_type"] = contract_type_from_rubric(row["rubric_name"])
    return rows


def get_task_detail(task_id: int, db: Any = DEFAULT_DB) -> dict:
    """Full task context for the decision page.

    The model verdict and reasoning are dropped for ``validity`` rows that are
    still ``pending`` — a blind form that showed them would turn independent
    annotation into endorsement (design D2). Once decided, they are included so
    the annotator can see whether they agreed.
    """
    ensure_schema(db)
    conn = connect(db)
    try:
        cur = conn.execute(
            "SELECT t.id, t.batch_id, t.batch_type, t.slot, t.status, "
            "       t.annotator, t.annotator_verdict, t.note, t.reviewed_at, "
            "       r.id AS eval_criteria_result_id, r.run_id, r.criterion_id, "
            "       r.title AS criterion_title, r.verdict AS model_verdict, "
            "       r.reasoning AS model_reasoning, r.ordinal, "
            "       e.rubric_name, e.draft_text, e.scored_at, e.judge_model, "
            "       c.description AS criterion_description, c.guidance AS criterion_guidance "
            "FROM review_tasks t "
            "JOIN eval_criteria_results r ON r.id = t.eval_criteria_result_id "
            "JOIN eval_runs e ON e.id = r.run_id "
            "LEFT JOIN rubrics rb ON rb.name = e.rubric_name "
            "LEFT JOIN criteria c ON c.rubric_id = rb.id AND c.name = r.criterion_id "
            "WHERE t.id = %s",
            (task_id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        raise NotFoundError(f"review task not found: {task_id}")
    row["contract_type"] = contract_type_from_rubric(row["rubric_name"])
    row["blind"] = row["batch_type"] == "validity" and row["status"] == "pending"
    if row["blind"]:
        row["model_verdict"] = None
        row["model_reasoning"] = None
    row["allowed_verdicts"] = list(_verdicts_for(row["batch_type"]))
    return row


def decide_task(
    *,
    task_id: int,
    annotator: str,
    verdict: str,
    note: Optional[str] = None,
    db: Any = DEFAULT_DB,
) -> dict:
    """Record a decision. Conditional on ``status='pending'`` (design D4).

    Returns ``{"ok": True, "task": <row>}`` on success, or
    ``{"ok": False, "decided_by": <annotator or None>}`` when another annotator
    already decided this slot — the caller turns that into a conflict response
    and the row is left untouched.
    """
    if not annotator:
        raise ValueError("annotator is required")
    detail = get_task_detail(task_id, db=db)
    if verdict not in _verdicts_for(detail["batch_type"]):
        raise ValueError(f"verdict {verdict!r} not allowed for {detail['batch_type']}")
    conn = connect(db)
    try:
        cur = conn.execute(
            "UPDATE review_tasks "
            "SET status = 'decided', annotator = %s, annotator_verdict = %s, "
            "    note = %s, reviewed_at = %s "
            "WHERE id = %s AND status = 'pending' "
            "RETURNING id",
            (
                annotator,
                verdict,
                (note or "").strip() or None,
                datetime.now(timezone.utc),
                task_id,
            ),
        )
        row = cur.fetchone()
        conn.commit()
        if row is None:
            cur = conn.execute(
                "SELECT annotator FROM review_tasks WHERE id = %s", (task_id,)
            )
            other = cur.fetchone()
            return {"ok": False, "decided_by": (other or {}).get("annotator")}
        return {"ok": True, "task": get_task_detail(task_id, db=db)}
    finally:
        conn.close()
