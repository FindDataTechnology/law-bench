"""Dependency injection for API routes."""

from typing import Any, Generator

from src.eval.db import connect


async def get_db() -> Generator[Any, None, None]:
    """Get database connection with automatic cleanup.

    Returns a generator that yields a psycopg connection and ensures
    proper cleanup in a finally block.
    """
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def get_settings():
    """API settings singleton from config module."""
    from .config import get_settings

    return get_settings()
