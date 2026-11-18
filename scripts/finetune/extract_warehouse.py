#!/usr/bin/env python3
"""Read-only warehouse extraction for the finetune data-prep subsystem.

Runs inside the law-bench pod::

    kubectl -n law-bench exec deployment/law-bench -- \
        python scripts/finetune/extract_warehouse.py

so it reuses the pod's ``database_url`` env var — credentials never leave
the cluster (design D5). Read-only by construction: the only SQL here is
``SELECT``; the only writes are to local JSONL files under ``data/finetune``.
No write/modify/remove SQL touches any existing table (spec: 仓库只读抽取任务).

Exports the six warehouse tables to ``data/finetune/warehouse/<table>.jsonl``
(one material record per row, each tagged with provenance / source / license
/ tier), writes a thin provenance index ``warehouse_manifest.jsonl``, and
refreshes ``coverage_gaps.jsonl``. Re-running over the same DB yields
byte-identical output (spec scenario 幂等只读抽取).
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

# Sibling import: put this script's dir on sys.path so `from common import`
# works both locally and in-pod.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from common import (  # noqa: E402
    COVERAGE_GAPS,
    MANIFEST_DIR,
    TIER_BY_TABLE,
    WAREHOUSE_DIR,
    WAREHOUSE_MANIFEST,
    write_jsonl,
)

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402


# Tables exported, in stable order. Each maps to a tier via TIER_BY_TABLE.
TABLES = (
    "clauses",
    "pipeline_runs",
    "eval_runs",
    "eval_criteria_results",
    "rubrics",
    "criteria",
    # widen: expand-finetune-data-sources §1.2
    "type_validations",
    "law_info",
    "contract_artifacts",
    "core_clauses",
    "industry_standard_references",
)

# Custom-stance thinness threshold (spec: 覆盖缺口记录 — custom 偏薄, 阈值 500).
CUSTOM_THIN_THRESHOLD = 500


def _dsn() -> str:
    """Database URL from the pod env (never hardcoded, never printed)."""
    dsn = os.environ.get("database_url") or os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit(
            "database_url not set in env — run inside the law-bench pod "
            "(kubectl -n law-bench exec deployment/law-bench -- ...)"
        )
    return dsn


def _connect(dsn: str):
    """Open a read-only dict-row connection.

    Mirrors the proven pattern in ``src/eval/db.py`` (autocommit + keepalives)
    without coupling the data-prep subsystem to the eval module's internals.
    """
    return psycopg.connect(
        dsn,
        row_factory=dict_row,
        autocommit=True,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5,
    )


def _fetch_table(conn, table: str) -> list[dict]:
    """Fetch every row of ``table`` ordered by id (stable, idempotent)."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT * FROM {table} ORDER BY id")  # nosec: B608
        # table is a hard-coded literal from TABLES, not user input.
        return list(cur.fetchall())


def _material_record(table: str, row: dict) -> dict:
    """Wrap a DB row as a tier-tagged material record."""
    row_id = row["id"]
    return {
        "provenance": f"{table}:{row_id}",
        "source": "warehouse",
        "license": "proprietary",
        "tier": TIER_BY_TABLE[table],
        "table": table,
        "row_id": row_id,
        "row": row,
    }


def _manifest_entry(table: str, row_id, tier: str) -> dict:
    """Thin provenance index record (matches manifest.schema.json)."""
    return {
        "dataset": "warehouse",
        "source": "warehouse",
        "license": "proprietary",
        "tier": tier,
        "provenance": f"{table}:{row_id}",
        "row_ref": f"warehouse/{table}.jsonl#{row_id}",
    }


def _coverage_gaps(material_by_table: dict[str, list[dict]]) -> list[dict]:
    """Compute coverage gaps from already-fetched material (no extra SQL).

    - ``zero_pipeline_runs``: contract types present in ``clauses`` but absent
      from ``pipeline_runs``.
    - ``custom_thin``: clauses whose ``tags.source == 'custom'`` fall below the
      threshold (500), with the actual count recorded.
    """
    gaps: list[dict] = []

    clause_rows = material_by_table.get("clauses", [])
    pipeline_rows = material_by_table.get("pipeline_runs", [])

    clause_type_rows: dict[str, int] = {}
    for r in clause_rows:
        ct = r["row"].get("contract_type")
        if ct:
            clause_type_rows[ct] = clause_type_rows.get(ct, 0) + 1
    pipeline_types = {
        r["row"].get("contract_type")
        for r in pipeline_rows
        if r["row"].get("contract_type")
    }

    for ct in sorted(clause_type_rows):
        if ct not in pipeline_types:
            gaps.append(
                {
                    "gap": "zero_pipeline_runs",
                    "contract_type": ct,
                    "clause_rows": clause_type_rows[ct],
                }
            )

    custom_count = 0
    for r in clause_rows:
        tags = r["row"].get("tags")
        if isinstance(tags, dict) and tags.get("source") == "custom":
            custom_count += 1
    if custom_count < CUSTOM_THIN_THRESHOLD:
        gaps.append(
            {
                "gap": "custom_thin",
                "threshold": CUSTOM_THIN_THRESHOLD,
                "actual": custom_count,
            }
        )

    return gaps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only warehouse extraction.")
    parser.add_argument(
        "--out-dir",
        default=str(WAREHOUSE_DIR),
        help="output dir for per-table material JSONL (default: %(default)s)",
    )
    parser.add_argument(
        "--manifest-dir",
        default=str(MANIFEST_DIR),
        help="output dir for manifest + coverage gaps (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    out_dir = pathlib.Path(args.out_dir)
    manifest_dir = pathlib.Path(args.manifest_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    conn = _connect(_dsn())
    try:
        material_by_table: dict[str, list[dict]] = {}
        manifest_entries: list[dict] = []

        for table in TABLES:
            rows = _fetch_table(conn, table)
            records = [_material_record(table, row) for row in rows]
            material_by_table[table] = records

            write_jsonl(out_dir / f"{table}.jsonl", records)

            tier = TIER_BY_TABLE[table]
            for rec in records:
                manifest_entries.append(_manifest_entry(table, rec["row_id"], tier))
            print(f"  {table}: {len(records)} rows -> {out_dir / f'{table}.jsonl'}")

        manifest_entries.sort(key=lambda r: (r["provenance"], r["tier"]))
        manifest_path = manifest_dir / WAREHOUSE_MANIFEST.name
        write_jsonl(manifest_path, manifest_entries)
        print(f"  manifest: {len(manifest_entries)} entries -> {manifest_path}")

        gaps = _coverage_gaps(material_by_table)
        gaps_path = manifest_dir / COVERAGE_GAPS.name
        write_jsonl(gaps_path, gaps)
        print(f"  coverage_gaps: {len(gaps)} gaps -> {gaps_path}")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
