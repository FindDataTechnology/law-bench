"""Harbor rubric seeding - the single source of truth for the schema and harbor's
reference rubrics.

Moved out of ``scripts/extract_harbor_rules.py`` so the web app and tests can
import it. Harbor's rubrics are loaded from the installed harbor package when it
is available (freshness for dev/CI), falling back to a bundled seed copy shipped
in the repo (so the Docker image - which does not install harbor - can still
self-heal harbor rubrics on startup).

The bundled TOMLs under ``seed/harbor/`` are pinned to ``BUNDLED_HARBOR_VERSION``
and are verbatim copies of harbor's shipped rubric files.

Run as a module to (re)seed a database::

    python -m src.eval.harbor_seed --db /app/db/evaluation_rules.db
    python -m src.eval.harbor_seed --db /path/to/other.db

The ``--db`` flag is retained for CLI compatibility but is no longer a file
path: the target is the PostgreSQL database addressed by ``database_url``.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from src.settings import DEFAULT_DB  # retained as the legacy default param value

from .db import column_exists, connect

# --------------------------------------------------------------------------- #
# Bundled seed (fallback when harbor is not installed)
# --------------------------------------------------------------------------- #

_HERE = Path(__file__).resolve().parent
BUNDLED_SEED_DIR = _HERE / "seed" / "harbor"

# The harbor version the bundled TOMLs are pinned to. When the installed harbor
# package is used instead, the real version is read from its dist-info METADATA.
BUNDLED_HARBOR_VERSION = "v0.20.0"

# Harbor's two shipped rubrics. Each TOML contains only ``[[criteria]]`` blocks,
# so the rubric-level metadata (name/context/description) lives here.
#
# ``source_path`` is the harbor-package-relative path (portable, stored in the DB
# as provenance) and also the locator used when harbor is installed. ``bundled_path``
# is the filename of the verbatim copy under ``BUNDLED_SEED_DIR`` used as a fallback.
HARBOR_RUBRICS: list[dict[str, str]] = [
    {
        "name": "task_quality",
        "context": "check",
        "source_path": "cli/quality_checker/default-rubric.toml",
        "bundled_path": "task_quality.toml",
        "description": (
            "Harbor's default rubric for checking task-definition quality "
            "(harbor check). Judges whether a benchmark task is well-designed: "
            "behavior coverage, anti-cheating, pinned deps, typos, etc."
        ),
    },
    {
        "name": "trial_behavior",
        "context": "analyze",
        "source_path": "analyze/prompts/analyze-rubric.toml",
        "bundled_path": "trial_behavior.toml",
        "description": (
            "Harbor's rubric for analyzing a trial's behavior (harbor analyze): "
            "reward hacking and task-specification sufficiency."
        ),
    },
]


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #

SCHEMA = """
CREATE TABLE IF NOT EXISTS rubrics (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT NOT NULL,
    context     TEXT NOT NULL,
    source      TEXT NOT NULL,
    source_path TEXT,
    description TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS criteria (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rubric_id   BIGINT NOT NULL REFERENCES rubrics(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT NOT NULL,
    guidance    TEXT NOT NULL,
    ordinal     INTEGER NOT NULL,
    UNIQUE(rubric_id, name)
);

CREATE TABLE IF NOT EXISTS prompts (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    contract_type TEXT NOT NULL,
    purpose       TEXT NOT NULL,
    content       TEXT NOT NULL,
    source        TEXT NOT NULL,
    prompt_type   TEXT,
    description   TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS law_info (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    contract_type TEXT NOT NULL,
    source        TEXT NOT NULL,
    zh_name       TEXT,
    content       TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    UNIQUE(contract_type, source)
);
"""


def project_root() -> Path:
    """src/eval/harbor_seed.py -> repo root."""
    return Path(__file__).resolve().parents[2]


def _ensure_column(conn, table: str, col: str, ddl: str) -> None:
    """Add ``col`` to ``table`` if it is missing (idempotent additive migration).

    ``CREATE TABLE IF NOT EXISTS`` will not add columns to a table that already
    exists, so additive columns added after a table's first release need a
    guarded ``ALTER TABLE``. This keeps ``create_schema`` self-healing for
    databases created before the column existed (e.g. predating
    ``prompts.prompt_type``).
    """
    if not column_exists(conn, table, col):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


def create_schema(conn) -> None:
    conn.execute(SCHEMA)
    # Converge additive columns on pre-existing tables (no-op on fresh DBs).
    _ensure_column(conn, "prompts", "prompt_type", "TEXT")
    conn.commit()


# --------------------------------------------------------------------------- #
# Harbor package discovery (returns None when harbor is not installed)
# --------------------------------------------------------------------------- #

def _uv_tool_dir() -> Path:
    """Return the uv tools dir via `uv tool dir`, falling back to the default."""
    try:
        out = subprocess.run(
            ["uv", "tool", "dir"],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        path = Path(out.stdout.strip())
        if path.is_dir():
            return path
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass
    return Path.home() / ".local" / "share" / "uv" / "tools"


def find_harbor_package() -> Path | None:
    """Locate the installed harbor package directory, or return ``None``.

    Returns ``None`` (rather than raising) when harbor is not installed, so
    callers can fall back to the bundled seed without special-casing the error.
    """
    tools_dir = _uv_tool_dir()
    candidates = [
        p for p in tools_dir.glob("harbor/lib/python*/site-packages/harbor")
        if p.is_dir()
    ]
    if not candidates:
        return None
    # Prefer the newest Python if multiple are present.
    return sorted(candidates)[-1]


def get_harbor_version(site_packages: Path) -> str:
    """Read harbor's version from its dist-info METADATA -> 'harbor:vX.Y.Z'."""
    for meta in site_packages.glob("harbor-*.dist-info/METADATA"):
        try:
            text = meta.read_text(encoding="utf-8")
        except OSError:
            continue
        m = re.search(r"^Version:\s*(.+)$", text, re.MULTILINE)
        if m:
            return f"harbor:v{m.group(1).strip()}"
    return "harbor:unknown"


# --------------------------------------------------------------------------- #
# Loading + upserting
# --------------------------------------------------------------------------- #

def load_criteria(toml_path: Path) -> list[dict[str, object]]:
    """Parse a harbor rubric TOML into ordered criterion dicts."""
    data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    criteria = []
    for i, c in enumerate(data.get("criteria", [])):
        criteria.append(
            {
                "name": c["name"],
                "description": c.get("description", ""),
                "guidance": c.get("guidance", ""),
                "ordinal": i,
            }
        )
    return criteria


def upsert_harbor_rubric(
    conn,
    rubric: dict[str, str],
    criteria: list[dict[str, object]],
    source: str,
    now_iso: str,
) -> int:
    """Upsert a harbor rubric and replace its criteria. Returns the rubric id.

    Matches existing rows by `name` AND `source LIKE 'harbor:%'`, so a local
    rubric that happens to share a name is never touched. Local/runtime rows
    are preserved.
    """
    row = conn.execute(
        "SELECT id FROM rubrics WHERE name = %s AND source LIKE 'harbor:%%'",
        (rubric["name"],),
    ).fetchone()
    if row:
        rubric_id = row["id"]
        conn.execute(
            "UPDATE rubrics SET context = %s, source = %s, source_path = %s, "
            "description = %s WHERE id = %s",
            (rubric["context"], source, rubric["source_path"],
             rubric["description"], rubric_id),
        )
    else:
        cur = conn.execute(
            "INSERT INTO rubrics (name, context, source, source_path, "
            "description, created_at) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (rubric["name"], rubric["context"], source, rubric["source_path"],
             rubric["description"], now_iso),
        )
        rubric_id = cur.fetchone()["id"]

    # Replace this harbor rubric's criteria wholesale so they always mirror the
    # TOML exactly (handles added/removed/renamed criteria on re-extraction).
    conn.execute("DELETE FROM criteria WHERE rubric_id = %s", (rubric_id,))
    for c in criteria:
        conn.execute(
            "INSERT INTO criteria (rubric_id, name, description, guidance, "
            "ordinal) VALUES (%s, %s, %s, %s, %s)",
            (rubric_id, c["name"], c["description"], c["guidance"], c["ordinal"]),
        )
    return rubric_id


def load_harbor_rubrics() -> tuple[list[tuple[dict[str, str], list[dict[str, object]], str]], str]:
    """Load every harbor rubric's criteria and provenance source string.

    Prefers the installed harbor package (so dev/CI track the real, current
    harbor version); falls back to the bundled seed TOMLs when harbor is not
    installed (the Docker image case).

    Returns ``(loaded, origin)`` where ``loaded`` is a list of
    ``(rubric_meta, criteria, source)`` tuples and ``origin`` is either
    ``"installed"`` or ``"bundled"``.
    """
    harbor_pkg = find_harbor_package()
    if harbor_pkg is not None:
        site_packages = harbor_pkg.parent
        source = get_harbor_version(site_packages)
        loaded: list[tuple[dict[str, str], list[dict[str, object]], str]] = []
        for rubric in HARBOR_RUBRICS:
            toml_path = harbor_pkg / rubric["source_path"]
            if not toml_path.is_file():
                print(f"WARNING: rubric file not found in installed harbor: {toml_path}",
                      file=sys.stderr)
                continue
            loaded.append((rubric, load_criteria(toml_path), source))
        if loaded:
            return loaded, "installed"
        # harbor present but its rubric files are missing -> fall through to bundle.

    source = f"harbor:{BUNDLED_HARBOR_VERSION}"
    loaded = []
    for rubric in HARBOR_RUBRICS:
        toml_path = BUNDLED_SEED_DIR / rubric["bundled_path"]
        if not toml_path.is_file():
            print(f"WARNING: bundled rubric file not found: {toml_path}", file=sys.stderr)
            continue
        loaded.append((rubric, load_criteria(toml_path), source))
    return loaded, "bundled"


def ensure_harbor_rubrics(db_path=DEFAULT_DB) -> dict:
    """Idempotently ensure harbor's rubrics are present in the target database.

    The target is the PostgreSQL database addressed by ``database_url``;
    ``db_path`` is accepted for signature compatibility (an optional live
    connection may be passed) but is no longer a file path. Creates the schema
    if absent, then upserts every harbor rubric (from the installed harbor
    package when available, else the bundled seed). The heal is scoped to
    ``source LIKE 'harbor:%'`` rows; local rubrics, prompts, and evaluation-run
    data are never modified or deleted.

    Returns a summary: ``{"rubrics": int, "criteria": int, "source_origin": str}``.
    """
    conn = connect(db_path)
    try:
        create_schema(conn)
        now_iso = datetime.now(timezone.utc).isoformat()
        loaded, origin = load_harbor_rubrics()
        total_criteria = 0
        for rubric, criteria, source in loaded:
            upsert_harbor_rubric(conn, rubric, criteria, source, now_iso)
            total_criteria += len(criteria)
        conn.commit()
        return {"rubrics": len(loaded), "criteria": total_criteria, "source_origin": origin}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Reporting + CLI
# --------------------------------------------------------------------------- #

def print_summary(conn) -> None:
    rows = conn.execute(
        "SELECT r.name, r.context, r.source, r.source_path, "
        "(SELECT COUNT(*) FROM criteria c WHERE c.rubric_id = r.id) AS n "
        "FROM rubrics r ORDER BY r.id"
    ).fetchall()
    print(f"\nRubrics ({len(rows)}):")
    for r in rows:
        print(f"  - {r['name']:18} [{r['context']:8}] {r['source']:18} "
              f"({r['n']} criteria)  <- {r['source_path']}")
    total = conn.execute("SELECT COUNT(*) AS n FROM criteria").fetchone()["n"]
    print(f"\nTotal criteria: {total}")
    n_prompts = conn.execute("SELECT COUNT(*) AS n FROM prompts").fetchone()["n"]
    print(f"Total prompts: {n_prompts}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help="(legacy, ignored) formerly the SQLite DB path; the target is now "
             "the PostgreSQL database addressed by database_url.",
    )
    args = ap.parse_args()

    summary = ensure_harbor_rubrics(args.db)
    origin = summary["source_origin"]
    if origin == "installed":
        print("Loaded harbor rubrics from the installed harbor package.")
    else:
        print(
            "harbor package not found; loaded harbor rubrics from the bundled "
            f"seed (pinned to harbor:{BUNDLED_HARBOR_VERSION})."
        )

    conn = connect(args.db)
    try:
        print_summary(conn)
    finally:
        conn.close()
    print(
        f"\nEnsured {summary['rubrics']} harbor rubrics / {summary['criteria']} criteria "
        f"(origin={origin})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
