"""Boot-time schema landing (2026-11-08 production incident).

Every ``/d`` page 500'd on a freshly rolled image because the production
database predated C5: ``domain_members`` had no ``last_opened_at`` and none of
the C5 tables existed. The DDL only ever ran against dev/test databases, whose
fixtures call ``ensure_schema`` explicitly — nothing guaranteed it on a deploy.

These tests pin the two halves of the fix:
1. the boot step really lands the whole C5 surface on an empty database;
2. the entrypoint runs it on the origin branch and NOT on the public read-only
   branch (a read surface must not perform DDL on a replicated dump).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = REPO_ROOT / "scripts" / "docker-entrypoint.sh"

C5_TABLES = (
    "domain_assets",
    "domain_proposals",
    "domain_proposal_events",
    "distribution_pull_events",
    "rag_corpora",
    "ontology_publications",
)


def _clean_dsn(conn) -> str:
    """A URI DSN without query params for the fixture's database.

    ``conn.info.dsn`` round-trips whatever form the suite connected with, and a
    conninfo (key=value) form carries the ``?``/``&`` keepalives the app appends;
    reusing it verbatim would test libpq's parser, not the boot step.
    """
    i = conn.info
    auth = i.user if i.password is None else f"{i.user}:{i.password}"
    return f"postgresql://{auth}@{i.host}:{i.port}/{i.dbname}"


def _tables(conn) -> set[str]:
    cur = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public'"
    )
    return {r["table_name"] for r in cur.fetchall()}


def _columns(conn, table: str) -> set[str]:
    cur = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s",
        (table,),
    )
    return {r["column_name"] for r in cur.fetchall()}


def test_boot_step_lands_the_whole_c5_schema_on_an_empty_database(empty_db, monkeypatch):
    """A database that predates C5 gets everything the /d surface reads."""
    from src.eval import bootstrap
    from src.eval.db import close_shared_conn

    monkeypatch.setenv("database_url", _clean_dsn(empty_db))
    # The boot step is a fresh process in production; in a test session the
    # process-wide shared connection may already point at another database, and
    # ensure_schema's per-dbname memo would then short-circuit. Release it so
    # the step re-opens from the DSN we just set.
    close_shared_conn()
    before = _tables(empty_db)
    assert not (set(C5_TABLES) & before), f"fixture was not empty: {before}"
    assert "last_opened_at" not in _columns(empty_db, "domain_members") or (
        "domain_members" not in before
    )

    assert bootstrap.main() == 0
    # ensure_schema keeps a process-wide shared connection; release it or the
    # fixture cannot drop its per-test database at teardown.
    from src.eval.db import close_shared_conn

    close_shared_conn()

    # Re-read through a fresh connection: the boot step must COMMIT, not leave
    # the DDL in an open transaction that dies with the process.
    with psycopg.connect(_clean_dsn(empty_db), row_factory=dict_row) as fresh:
        after = _tables(fresh)
        assert set(C5_TABLES) <= after, f"boot step missed: {set(C5_TABLES) - after}"
        assert "last_opened_at" in _columns(fresh, "domain_members")


def test_boot_step_is_idempotent(empty_db, monkeypatch):
    """Running twice (two replicas rolling at once) is a no-op, not an error."""
    from src.eval import bootstrap

    from src.eval.db import close_shared_conn

    monkeypatch.setenv("database_url", _clean_dsn(empty_db))
    close_shared_conn()
    assert bootstrap.main() == 0
    assert bootstrap.main() == 0

    from src.eval.db import close_shared_conn

    close_shared_conn()


FLEET_LOOP_COLUMNS = {
    "authoring_tasks": {"assignee_kind", "assignee_ref"},
    "distribution_consumers": {"kind", "fleet_ref"},
    "domain_agent_runs": {"origin", "runner_ref"},
}


def test_boot_step_lands_the_fleet_loop_columns(empty_db, monkeypatch):
    """add-fleet-execution-loop §0.2: six columns, on an empty database."""
    from src.eval import bootstrap
    from src.eval.db import close_shared_conn

    monkeypatch.setenv("database_url", _clean_dsn(empty_db))
    close_shared_conn()
    assert bootstrap.main() == 0
    close_shared_conn()

    with psycopg.connect(_clean_dsn(empty_db), row_factory=dict_row) as fresh:
        for table, expected in FLEET_LOOP_COLUMNS.items():
            got = _columns(fresh, table)
            assert expected <= got, f"{table} missing {expected - got}"


def test_existing_rows_take_the_documented_defaults(empty_db, monkeypatch):
    """The columns are added with defaults so pre-existing rows stay readable.

    A NULL ``assignee_kind`` or ``origin`` would make every old row unreadable by
    the new read paths, which is the exact failure mode this DDL avoids.
    """
    from src.eval import bootstrap
    from src.eval.db import close_shared_conn

    monkeypatch.setenv("database_url", _clean_dsn(empty_db))
    close_shared_conn()
    assert bootstrap.main() == 0
    close_shared_conn()

    with psycopg.connect(_clean_dsn(empty_db), row_factory=dict_row) as fresh:
        fresh.execute(
            "INSERT INTO ontology_templates (name, version, schema, created_by) "
            "VALUES ('t1', 1, '{}'::jsonb, 'tester')"
        )
        fresh.execute(
            "INSERT INTO domains (key, name, template_id, template_version, created_by) "
            "SELECT 'd1', 'D1', id, 1, 'tester' FROM ontology_templates WHERE name='t1'"
        )
        fresh.execute(
            "INSERT INTO authoring_tasks (domain_id, assignee, title, created_by) "
            "SELECT id, 'someone', 't', 'tester' FROM domains WHERE key='d1'"
        )
        fresh.execute(
            "INSERT INTO distribution_consumers (name, domains, token_hash, created_by) "
            "VALUES ('c1', '{d1}', 'hash-c1', 'tester')"
        )
        fresh.execute(
            "INSERT INTO domain_agent_runs (role, domain_key) VALUES ('r1', 'd1')"
        )
        fresh.commit()

        task = fresh.execute(
            "SELECT assignee_kind, assignee_ref FROM authoring_tasks"
        ).fetchone()
        assert task["assignee_kind"] == "human" and task["assignee_ref"] is None

        consumer = fresh.execute(
            "SELECT kind, fleet_ref FROM distribution_consumers"
        ).fetchone()
        assert consumer["kind"] == "machine" and consumer["fleet_ref"] is None

        run = fresh.execute(
            "SELECT origin, runner_ref FROM domain_agent_runs"
        ).fetchone()
        assert run["origin"] == "kernel" and run["runner_ref"] is None


def test_one_live_registration_per_fleet(empty_db, monkeypatch):
    """A second live registration for the same fleet is refused by the index.

    Revoking the first must free the fleet_ref again — a revoked credential is
    not a live claim on the identity.
    """
    from src.eval import bootstrap
    from src.eval.db import close_shared_conn

    monkeypatch.setenv("database_url", _clean_dsn(empty_db))
    close_shared_conn()
    assert bootstrap.main() == 0
    close_shared_conn()

    with psycopg.connect(_clean_dsn(empty_db), row_factory=dict_row) as fresh:
        fresh.execute(
            "INSERT INTO distribution_consumers (name, domains, token_hash, kind, fleet_ref, created_by) "
            "VALUES ('c1','{d1}','h1','fleet','fleet_1','t')"
        )
        fresh.commit()
        with pytest.raises(psycopg.errors.UniqueViolation):
            fresh.execute(
                "INSERT INTO distribution_consumers (name, domains, token_hash, kind, fleet_ref, created_by) "
                "VALUES ('c2','{d1}','h2','fleet','fleet_1','t')"
            )
        fresh.rollback()
        fresh.execute("UPDATE distribution_consumers SET revoked_at = now() WHERE name='c1'")
        fresh.execute(
            "INSERT INTO distribution_consumers (name, domains, token_hash, kind, fleet_ref, created_by) "
            "VALUES ('c2','{d1}','h2','fleet','fleet_1','t')"
        )
        fresh.commit()
        n = fresh.execute(
            "SELECT count(*) AS n FROM distribution_consumers WHERE fleet_ref='fleet_1'"
        ).fetchone()["n"]
        assert n == 2, "the revoked row must stay for audit"


def test_boot_step_fails_loudly_when_the_database_is_unreachable(monkeypatch):
    """No schema, no traffic: an unreachable database must not exit 0."""
    from src.eval import bootstrap

    monkeypatch.setenv(
        "database_url",
        "postgresql://nobody:nothing@127.0.0.1:1/definitely_absent",
    )
    monkeypatch.setenv("PGPORT", "1")
    out = subprocess.run(
        [sys.executable, "-m", "src.eval.bootstrap"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ},
    )
    assert out.returncode != 0, out.stdout + out.stderr


def _entrypoint_branches() -> tuple[list[str], list[str]]:
    """Split the entrypoint into (public-branch lines, origin-branch lines)."""
    text = ENTRYPOINT.read_text(encoding="utf-8")
    body = [
        line
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    public: list[str] = []
    origin: list[str] = []
    in_public = False
    for line in body:
        if line.startswith("if [") and "PUBLIC_API" in line:
            in_public = True
            continue
        if in_public and line.strip() == "fi":
            in_public = False
            continue
        (public if in_public else origin).append(line)
    return public, origin


def test_entrypoint_ensures_schema_on_the_origin_branch():
    _, origin = _entrypoint_branches()
    joined = "\n".join(origin)
    assert re.search(r"-m src\.eval\.bootstrap", joined), (
        "the origin branch must land the additive schema before serving"
    )
    # and it must come before uvicorn takes traffic
    assert joined.index("src.eval.bootstrap") < joined.index("uvicorn")


def test_entrypoint_never_runs_ddl_on_the_public_pod():
    public, _ = _entrypoint_branches()
    joined = "\n".join(public)
    assert "-m src.eval.bootstrap" not in joined
    assert "ensure_schema" not in joined
