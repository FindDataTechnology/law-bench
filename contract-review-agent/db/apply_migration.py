"""Apply the agent_runs schema migration to the shared PostgreSQL database.

Usage:
    python -m db.apply_migration            # applies all .sql files in db/
    python db/apply_migration.py            # same, run directly
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parent

# Make the law-template repo importable so `import psycopg` etc. resolve.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import psycopg  # noqa: E402


def apply_migrations(database_url: str | None = None) -> None:
    dsn = database_url or os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set; copy .env.example -> .env")

    sql_files = sorted(THIS_DIR.glob("*.sql"))
    if not sql_files:
        print("No .sql migration files found.")
        return

    with psycopg.connect(dsn) as conn:
        conn.autocommit = True
        for sql_file in sql_files:
            print(f"Applying {sql_file.name} ...")
            conn.execute(sql_file.read_text(encoding="utf-8"))
            print(f"  done: {sql_file.name}")
    print("All migrations applied.")


if __name__ == "__main__":
    apply_migrations()
