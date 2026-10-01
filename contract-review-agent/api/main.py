"""FastAPI application for the contract-review-agent.

Exposes:
- /api/health — liveness probe
- /api/agent-runs — CRUD for agent_runs metrics (via MCP tool wrappers)
- / — CopilotKit AG-UI endpoint (LangGraph graph)

The graph is compiled with AsyncPostgresSaver at startup so interrupt() can
pause/resume across HTTP requests.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import config


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: initialize checkpointer + apply DB migrations."""
    from agent.checkpointer import get_checkpointer
    from agent.store import ensure_agent_runs_schema

    # Apply agent_runs schema (idempotent CREATE TABLE IF NOT EXISTS).
    await _run_migrations()
    ensure_agent_runs_schema()

    # Initialize the LangGraph checkpointer (opens Postgres connection).
    await get_checkpointer()

    yield

    # Shutdown: close checkpointer.
    from agent.checkpointer import close_checkpointer
    await close_checkpointer()


async def _run_migrations() -> None:
    """Apply SQL migrations from db/*.sql."""
    import asyncio
    from pathlib import Path

    import psycopg

    db_url = config.database_url
    if not db_url:
        return

    migrations_dir = Path(__file__).parent.parent / "db"
    if not migrations_dir.exists():
        return

    sql_files = sorted(migrations_dir.glob("*.sql"))
    if not sql_files:
        return

    def _apply():
        with psycopg.connect(db_url) as conn:
            for sql_file in sql_files:
                with open(sql_file) as f:
                    conn.execute(f.read())

    await asyncio.to_thread(_apply)


def create_app() -> FastAPI:
    """Build and configure the FastAPI app."""
    app = FastAPI(
        title="Contract Review Agent",
        description="Multi-model contract review with human-in-the-loop checkpoints",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS
    origins = [o.strip() for o in config.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API key auth (optional)
    if config.api_key_enabled:
        from .middleware import APIKeyMiddleware
        app.add_middleware(APIKeyMiddleware, api_keys=config.api_keys)

    # Register routes
    from .routes import agent_runs, chat, health

    app.include_router(health.router, prefix="/api")
    app.include_router(agent_runs.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.host, port=config.port)
