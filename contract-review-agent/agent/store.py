"""CRUD for the ``agent_runs`` table (per-run metrics for the review agent).

Reuses ``src.eval.db.connect`` (process-wide cached psycopg connection) so the
agent shares one TCP connection with the rest of law-bench, instead of opening
a fresh one per metric write. JSONB columns accept plain Python dicts/lists and
are serialized via ``psycopg.types.json.Jsonb``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

# Make the law-template repo importable so `from src.eval.db import connect`
# resolves when this module is imported from inside contract-review-agent.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from psycopg.types.json import Jsonb  # noqa: E402

from src.eval.db import connect  # noqa: E402

AGENT_RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_runs (
    id              BIGSERIAL PRIMARY KEY,
    thread_id       TEXT        NOT NULL,
    contract_type   TEXT        NOT NULL,
    tags            JSONB       NOT NULL DEFAULT '{}',
    task_desc       TEXT,
    node_timings    JSONB       NOT NULL DEFAULT '{}',
    model_calls     JSONB       NOT NULL DEFAULT '[]',
    review_suggestions      JSONB NOT NULL DEFAULT '[]',
    suggestions_applied     JSONB NOT NULL DEFAULT '[]',
    total_slots         INTEGER NOT NULL DEFAULT 0,
    human_filled_slots  INTEGER NOT NULL DEFAULT 0,
    eval_run_id     BIGINT REFERENCES eval_runs(id) ON DELETE SET NULL,
    deepeval_scores JSONB NOT NULL DEFAULT '{}',
    total_duration  REAL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_created_at ON agent_runs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_contract_type ON agent_runs (contract_type);
CREATE INDEX IF NOT EXISTS idx_agent_runs_thread_id ON agent_runs (thread_id);
"""


def ensure_agent_runs_schema(db: Any = None) -> None:
    """Create the ``agent_runs`` table if it does not exist (idempotent)."""
    conn = connect(db)
    try:
        conn.execute(AGENT_RUNS_SCHEMA)
        if db is None:
            conn.close() if not hasattr(conn, "_BorrowedConn__conn") else None
    except Exception:
        # Borrowed connections don't need commit (autocommit shared conn).
        # For a fresh connection we must commit the DDL.
        try:
            conn.commit()
        except Exception:
            pass
        raise
    finally:
        # Only close a connection we own (not the shared cached one).
        if db is None and not hasattr(conn, "_BorrowedConn__conn"):
            try:
                conn.close()
            except Exception:
                pass


def insert_agent_run(row: dict, db: Any = None) -> int:
    """Insert one ``agent_runs`` row; return its id.

    ``row`` keys: thread_id, contract_type, tags, task_desc, node_timings,
    model_calls, review_suggestions, suggestions_applied, total_slots,
    human_filled_slots, eval_run_id, deepeval_scores, total_duration.
    """
    ensure_agent_runs_schema(db)
    conn = connect(db)
    try:
        cur = conn.execute(
            "INSERT INTO agent_runs "
            "(thread_id, contract_type, tags, task_desc, node_timings, model_calls, "
            " review_suggestions, suggestions_applied, total_slots, human_filled_slots, "
            " eval_run_id, deepeval_scores, total_duration) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (
                row["thread_id"],
                row["contract_type"],
                Jsonb(row.get("tags") or {}),
                row.get("task_desc"),
                Jsonb(row.get("node_timings") or {}),
                Jsonb(row.get("model_calls") or []),
                Jsonb(row.get("review_suggestions") or []),
                Jsonb(row.get("suggestions_applied") or []),
                int(row.get("total_slots") or 0),
                int(row.get("human_filled_slots") or 0),
                row.get("eval_run_id"),
                Jsonb(row.get("deepeval_scores") or {}),
                row.get("total_duration"),
            ),
        )
        if db is None and not hasattr(conn, "_BorrowedConn__conn"):
            conn.commit()
        return cur.fetchone()["id"]
    finally:
        if db is None and not hasattr(conn, "_BorrowedConn__conn"):
            try:
                conn.close()
            except Exception:
                pass


def get_agent_run(run_id: int, db: Any = None) -> Optional[dict]:
    """One ``agent_runs`` row (full), or ``None`` if absent."""
    ensure_agent_runs_schema(db)
    conn = connect(db)
    try:
        r = conn.execute(
            "SELECT * FROM agent_runs WHERE id = %s",
            (run_id,),
        ).fetchone()
        return dict(r) if r else None
    finally:
        if db is None and not hasattr(conn, "_BorrowedConn__conn"):
            try:
                conn.close()
            except Exception:
                pass


def list_agent_runs(limit: int = 20, db: Any = None) -> list[dict]:
    """Recent ``agent_runs`` rows, newest-first (summary fields only)."""
    ensure_agent_runs_schema(db)
    conn = connect(db)
    try:
        rows = conn.execute(
            "SELECT id, thread_id, contract_type, task_desc, total_slots, "
            "       human_filled_slots, eval_run_id, total_duration, created_at "
            "FROM agent_runs ORDER BY id DESC LIMIT %s",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if db is None and not hasattr(conn, "_BorrowedConn__conn"):
            try:
                conn.close()
            except Exception:
                pass
