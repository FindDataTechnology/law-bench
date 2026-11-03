#!/usr/bin/env python3
"""Seed the per-contract-type 法律法规 survey answers (law_info) into the DB.

Reads the bundled markdown under ``src/eval/seed/law_info/`` - 41 contract
types × {doubao, deepseek} = 82 files - plus ``contract_types.json`` (the
``{key, zh}`` registry), and upserts one ``law_info`` row per
``(contract_type, source)``.

The bundled markdown is the canonical source: ``output/`` is gitignored and
absent from the container, so the files are committed under
``src/eval/seed/law_info/`` (mirroring the ``src/eval/seed/harbor/`` pattern).

Idempotent: upserts by the ``(contract_type, source)`` UNIQUE constraint -
UPDATE ``zh_name``/``content`` if the pair exists, else INSERT. Re-running
never duplicates and never touches ``rubrics``, ``criteria``, ``prompts``, or
``eval_runs``.

Reuses the schema helpers from extract_harbor_rules so the schema has one
source of truth.

Run:
    uv run python scripts/seed_law_info.py
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from extract_harbor_rules import DEFAULT_DB, create_schema, print_summary, project_root

SOURCES = ("doubao", "deepseek")
SEED_DIR = "src/eval/seed/law_info"


def _seed_dir() -> Path:
    return project_root() / SEED_DIR


def load_contract_types() -> list[dict]:
    """Return the ``[{key, zh}, ...]`` registry from the bundled JSON."""
    with (_seed_dir() / "contract_types.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def upsert_law_info(conn, contract_type: str, source: str, zh_name: str,
                    content: str, now_iso: str) -> int:
    """Upsert one law_info row by ``(contract_type, source)``. Returns the id."""
    row = conn.execute(
        "SELECT id FROM law_info WHERE contract_type = %s AND source = %s",
        (contract_type, source),
    ).fetchone()
    if row:
        lid = row["id"]
        conn.execute(
            "UPDATE law_info SET zh_name = %s, content = %s WHERE id = %s",
            (zh_name, content, lid),
        )
        return lid
    cur = conn.execute(
        "INSERT INTO law_info (contract_type, source, zh_name, content, created_at) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (contract_type, source, zh_name, content, now_iso),
    )
    return cur.fetchone()["id"]


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--db", type=Path, default=project_root() / DEFAULT_DB)
    args = ap.parse_args()

    from src.eval.db import connect

    contract_types = load_contract_types()
    seed = _seed_dir()
    conn = connect()
    try:
        create_schema(conn)
        now_iso = datetime.now(timezone.utc).isoformat()
        n = 0
        for ct in contract_types:
            key, zh = ct["key"], ct["zh"]
            for source in SOURCES:
                path = seed / source / f"{key}.md"
                content = path.read_text(encoding="utf-8")
                lid = upsert_law_info(conn, key, source, zh, content, now_iso)
                print(f"  upserted {key:24} [{source:7}] zh={zh} (law_info_id={lid})")
                n += 1
        conn.commit()
        print(f"\nSeeded {n} law_info rows ({len(contract_types)} types × {len(SOURCES)} sources) into {args.db}")
        print_summary(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
