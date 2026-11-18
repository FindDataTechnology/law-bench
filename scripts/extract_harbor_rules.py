#!/usr/bin/env python3
"""Extract harbor's evaluation rubrics into a SQLite database.

Thin CLI wrapper around :mod:`src.eval.harbor_seed`, which is the single source
of truth for the schema and harbor-rubric seeding logic. The logic lives in the
importable module so the web app and tests can call it directly; this script
keeps the ``uv run python scripts/extract_harbor_rules.py`` entry point.

Loads harbor's rubrics from the installed harbor package when it is available;
otherwise falls back to a bundled seed copy shipped in the repo (so this works
in the Docker image, which does not install harbor). Either way the run is
idempotent: it only touches rubrics whose ``source`` starts with ``harbor:``.
Local rubrics (``source = local``) and their criteria are never modified or
deleted.

Run:
    uv run python scripts/extract_harbor_rules.py
    uv run python scripts/extract_harbor_rules.py --db /path/to/other.db
"""

from __future__ import annotations

import sys
from pathlib import Path

# This script lives in scripts/, which is not a package. Make the repo root
# importable so `src.eval.harbor_seed` resolves whether the script is run
# directly, imported by a sibling seed script, or invoked via subprocess.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.eval.harbor_seed import (  # noqa: E402
    BUNDLED_HARBOR_VERSION,
    BUNDLED_SEED_DIR,
    DEFAULT_DB,
    HARBOR_RUBRICS,
    SCHEMA,
    create_schema,
    ensure_harbor_rubrics,
    find_harbor_package,
    get_harbor_version,
    load_criteria,
    load_harbor_rubrics,
    main,
    print_summary,
    project_root,
    upsert_harbor_rubric,
)

# Re-exported so legacy imports keep working:
#   `from extract_harbor_rules import DEFAULT_DB, create_schema, print_summary, project_root`
# (used by scripts/seed_contract_rubrics.py, scripts/seed_sample_local_rubric.py,
# and the test suite via importlib.util.spec_from_file_location).
__all__ = [
    "BUNDLED_HARBOR_VERSION",
    "BUNDLED_SEED_DIR",
    "DEFAULT_DB",
    "HARBOR_RUBRICS",
    "SCHEMA",
    "create_schema",
    "ensure_harbor_rubrics",
    "find_harbor_package",
    "get_harbor_version",
    "load_criteria",
    "load_harbor_rubrics",
    "main",
    "print_summary",
    "project_root",
    "upsert_harbor_rubric",
]


if __name__ == "__main__":
    raise SystemExit(main())
