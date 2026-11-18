"""PostgresSaver checkpointer for the review-agent graph.

Required for LangGraph ``interrupt()`` to pause/resume across HTTP requests.
The checkpointer stores per-``thread_id`` state snapshots in the same shared
PostgreSQL database as ``pipeline_runs`` / ``eval_runs``, so agent state and
metrics live alongside everything else.
"""
from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

load_dotenv()

# Singleton checkpointer. AsyncPostgresSaver.from_conn_string returns an async
# context manager; we enter it once and keep the saver for the process lifetime.
_CHECKPOINTER: Any = None
_SETUP_DONE = False


async def get_checkpointer() -> Any:
    """Return a singleton AsyncPostgresSaver, calling setup() once.

    Raises RuntimeError if DATABASE_URL is unset.
    """
    global _CHECKPOINTER, _SETUP_DONE
    if _CHECKPOINTER is not None:
        return _CHECKPOINTER

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    dsn = os.environ.get("DATABASE_URL") or os.environ.get("database_url")
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL is not set; copy .env.example -> .env"
        )

    # from_conn_string returns an async context manager. Enter it to get the
    # actual saver instance, then hold it for the process lifetime.
    ctx = AsyncPostgresSaver.from_conn_string(dsn)
    _CHECKPOINTER = await ctx.__aenter__()
    if not _SETUP_DONE:
        await _CHECKPOINTER.setup()
        _SETUP_DONE = True
    return _CHECKPOINTER


async def close_checkpointer() -> None:
    """Close the singleton checkpointer (server shutdown)."""
    global _CHECKPOINTER, _SETUP_DONE
    if _CHECKPOINTER is not None:
        try:
            await _CHECKPOINTER.__aexit__(None, None, None)
        except Exception:
            pass
    _CHECKPOINTER = None
    _SETUP_DONE = False
