#!/usr/bin/env python3
"""Stamp the pre-layering templates with their layer and authority.

Before layers existed, ``legal-domain`` and ``gov-domain`` were single flat
templates. Layer is a *new* field, so the migration is additive: every existing
version gets ``layer: "domain"`` and ``authority: {"kind": "platform"}`` and
nothing else changes — the six required keys stay byte-identical.

Why ``domain`` and not ``industry``: neither template's vocabulary is shared
with any other line. ``clause``/``law`` are the legal line's own words, and
``gov-fact``/``concept`` are the gov line's. An ``industry`` layer would claim
"sibling verticals inherit this", which is not true of either.

Why not ``extends foundation-v1``: a legal clause is not an organization, a
place, or a measurement. Forcing the legal vocabulary under the foundation's
eight generic types would add seven types nothing in the domain ever writes, and
the coverage pillar would then report them as declared-but-empty gaps forever.

Which templates get stamped is discovered, not hardcoded: every template name
that exists at migration time and carries no ``layer``. A future template that
already declares one is skipped (this script is idempotent and safe to re-run).

Run:
    uv run python scripts/migrate_template_layers.py --dry-run
    uv run python scripts/migrate_template_layers.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.bench import templates  # noqa: E402

CREATED_BY = "system:migrate-layers"

#: What every pre-layering template becomes. See the module docstring for why
#: `domain` and not `industry`.
LEGACY_LAYER = "domain"
LEGACY_AUTHORITY = {"kind": "platform"}


def plan(conn) -> list[tuple[dict, dict]]:
    """(current latest version, its schema with the two fields added)."""
    out = []
    for row in templates.list_templates(conn):
        schema = row["schema"] or {}
        if schema.get("layer"):
            continue  # already layered — nothing to migrate
        migrated = dict(schema)
        migrated["layer"] = LEGACY_LAYER
        migrated["authority"] = dict(LEGACY_AUTHORITY)
        out.append((row, migrated))
    return out


def eval_dsn() -> str:
    """The real PostgreSQL DSN (``database_url`` env), never the SQLite path constant."""
    from src.eval import db as edb

    return edb._dsn()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args(argv)

    import psycopg

    from src.eval import store as eval_store

    # DEFAULT_DB is the legacy SQLite path constant, NOT a DSN — passing it to
    # psycopg makes conninfo parsing blow up on a PosixPath. Read the real DSN.
    dsn = args.database_url or eval_dsn()
    conn = psycopg.connect(dsn, row_factory=psycopg.rows.dict_row)
    try:
        eval_store.ensure_schema(db_path=conn)
        pending = plan(conn)
        if not pending:
            print("no unlayered templates found — nothing to migrate")
            return 0

        for row, schema in pending:
            problems = templates.validate_template_schema(schema)
            if problems:
                print(f"REFUSING {row['name']}: " + "; ".join(problems), file=sys.stderr)
                return 1

        if args.dry_run:
            print("DRY-RUN — nothing written. Would stamp:")
            for row, _ in pending:
                print(f"  {row['name']} (latest v{row['version']}) → "
                      f"layer={LEGACY_LAYER} authority=platform")
            return 0

        for row, schema in pending:
            # A new version, never an edit of the old one: domains pin a version,
            # so rewriting a historical row would change what they inherit.
            created = templates.update_template(
                conn, name=row["name"], schema=schema, created_by=CREATED_BY
            )
            print(f"stamped {row['name']} v{created['version']} "
                  f"(was v{row['version']}) layer={LEGACY_LAYER}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
