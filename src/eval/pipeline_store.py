"""CRUD for the LangGraph contract-pipeline tables (``pipeline_runs`` / ``fill_cache``).

Schema is established by :func:`src.eval.store.ensure_schema` (PIPELINE_SCHEMA).
``pipeline_runs`` links to ``eval_runs`` via ``eval_run_id`` (the run produced by
``contract_evaluate``); ``fill_cache`` memoizes LLM slot-fills so identical inputs
are deterministic and amortize the LLM cost. Mirrors the connection /
``finally: conn.close()`` style of :mod:`src.eval.store`.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional

import psycopg
from psycopg.types.json import Jsonb

from .db import connect, close_shared_conn
from .store import ensure_schema


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _retry_on_conn_error(func, max_retries: int = 3, base_delay: float = 0.1):
    """Retry a database operation on connection errors (AdminShutdown, etc.)."""
    for attempt in range(max_retries + 1):
        try:
            return func()
        except (psycopg.errors.AdminShutdown, psycopg.errors.OperationalError) as e:
            if attempt == max_retries:
                raise
            try:
                close_shared_conn()
            except Exception:
                pass
            delay = base_delay * (2 ** attempt)
            time.sleep(delay)


def insert_pipeline_run(row: dict, db: Any = None) -> int:
    """Insert one ``pipeline_runs`` row; return its id.

    ``row`` carries the generation context + best-run result. Optional fields
    default to NULL. ``tags`` / ``fill_values`` / ``actions_taken`` /
    ``recommendations`` are JSONB.
    """
    ensure_schema(db)
    now = _now()

    def _do_insert():
        conn = connect(db)
        try:
            cur = conn.execute(
                "INSERT INTO pipeline_runs "
                "(contract_type, tags, stance, rubric_name, task_desc, fill_mode, "
                " fill_values, filled_text, eval_run_id, score, max_score, n_passed, "
                " n_criteria, all_pass, iteration, actions_taken, recommendations, "
                " fill_cache_id, fill_temperature, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "RETURNING id",
                (
                    row["contract_type"],
                    Jsonb(row.get("tags") or {}),
                    row.get("stance"),
                    row["rubric_name"],
                    row.get("task_desc"),
                    row.get("fill_mode"),
                    Jsonb(row.get("fill_values") or {}),
                    row.get("filled_text"),
                    row.get("eval_run_id"),
                    row.get("score"),
                    row.get("max_score"),
                    row.get("n_passed"),
                    row.get("n_criteria"),
                    row.get("all_pass"),
                    row.get("iteration", 1),
                    Jsonb(row.get("actions_taken") or []),
                    Jsonb(row.get("recommendations") or []),
                    row.get("fill_cache_id"),
                    row.get("fill_temperature"),
                    now,
                ),
            )
            conn.commit()
            return cur.fetchone()["id"]
        finally:
            if db is None:
                conn.close()

    return _retry_on_conn_error(_do_insert)


def list_pipeline_runs(limit: int = 20, db: Any = None) -> list[dict]:
    """Recent ``pipeline_runs`` rows, newest-first (run-level fields only)."""
    ensure_schema(db)
    conn = connect(db)
    try:
        rows = conn.execute(
            "SELECT id, contract_type, stance, rubric_name, task_desc, score, "
            "       max_score, n_passed, n_criteria, all_pass, iteration, "
            "       eval_run_id, fill_temperature, created_at "
            "FROM pipeline_runs ORDER BY id DESC LIMIT %s",
            (limit,),
        ).fetchall()
    finally:
        if db is None:
            conn.close()
    return [dict(r) for r in rows]


def get_pipeline_run(pipeline_id: int, db: Any = None) -> Optional[dict]:
    """One ``pipeline_runs`` row (full, incl. ``filled_text`` / ``fill_values`` /
    ``actions_taken`` / ``recommendations``), or ``None`` if absent."""
    ensure_schema(db)
    conn = connect(db)
    try:
        r = conn.execute(
            "SELECT * FROM pipeline_runs WHERE id = %s", (pipeline_id,)
        ).fetchone()
    finally:
        if db is None:
            conn.close()
    return dict(r) if r else None


def lookup_fill(cache_key: str, db: Any = None) -> Optional[dict]:
    """Return a cached fill ``{id, fill_values, temperature, model}`` or ``None``."""
    ensure_schema(db)
    conn = connect(db)
    try:
        r = conn.execute(
            "SELECT id, fill_values, temperature, model FROM fill_cache "
            "WHERE cache_key = %s",
            (cache_key,),
        ).fetchone()
    finally:
        if db is None:
            conn.close()
    return dict(r) if r else None


def insert_fill(
    cache_key: str,
    contract_type: str,
    scenario: Optional[str],
    slots_hash: str,
    fill_values: dict,
    temperature: Optional[float],
    model: Optional[str],
    db: Any = None,
) -> int:
    """Insert a ``fill_cache`` row; return its id."""
    ensure_schema(db)
    now = _now()
    conn = connect(db)
    try:
        cur = conn.execute(
            "INSERT INTO fill_cache "
            "(cache_key, contract_type, scenario, slots_hash, fill_values, "
            " temperature, model, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (
                cache_key,
                contract_type,
                scenario,
                slots_hash,
                Jsonb(fill_values),
                temperature,
                model,
                now,
            ),
        )
        conn.commit()
        return cur.fetchone()["id"]
    finally:
        if db is None:
            conn.close()
