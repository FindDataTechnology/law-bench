"""Concurrency tests for ``ensure_schema`` (fix-ensure-schema-lock-masking).

The defect these pin: when table creation hits the 3s ``lock_timeout``, the old
code swallowed ``LockNotAvailable`` and added the database to ``_ensured_dbs``
anyway — claiming "schema ready" while zero DDL had run, and never retrying for
the rest of the process's life. Every later write then failed with
``UndefinedTable`` far away from the cause.

These tests hold a real ACCESS EXCLUSIVE lock from a second connection and
assert the bootstrapper tells the truth about what it did.

Requires a local PostgreSQL (same as the rest of the DB-backed suite).
"""

from __future__ import annotations

import psycopg
import pytest

from src.eval import store as store_mod
from src.eval.store import ensure_schema

#: Short lock timeout so these tests don't each sit for the production 3s.
LOCK_TIMEOUT_MS = 200


@pytest.fixture()
def rapid_lock_timeout(monkeypatch):
    monkeypatch.setenv("SCHEMA_LOCK_TIMEOUT_MS", str(LOCK_TIMEOUT_MS))
    yield


@pytest.fixture()
def fresh_db(empty_db, monkeypatch):
    """A brand-new empty DB, NOT yet schema'd, and not in the ensured cache."""
    key = empty_db.info.dbname
    store_mod._ensured_dbs.discard(key)
    yield empty_db
    store_mod._ensured_dbs.discard(key)


def _password_from_database_url() -> str | None:
    """The password from ``database_url``; ``conn.info.dsn`` never carries it.

    Locally that omission is masked by trust auth, so these tests passed for
    months. On CI (Postgres service with password auth) the second connection
    fails with ``fe_sendauth: no password supplied`` and the tests look broken
    for a reason that has nothing to do with the lock path they pin.
    """
    import os
    from urllib.parse import urlsplit

    dsn = os.environ.get("database_url") or os.environ.get("DATABASE_URL") or ""
    if not dsn:
        return None
    try:
        return urlsplit(dsn).password
    except ValueError:
        return None


def _connect_for_lock(dsn: str):
    """A second connection to the same DB, carrying the password explicitly."""
    password = _password_from_database_url()
    return psycopg.connect(
        dsn, autocommit=False, **({"password": password} if password else {})
    )


def _hold_lock_on(dsn: str, table: str):
    """An open transaction holding ACCESS EXCLUSIVE on ``table``."""
    holder = _connect_for_lock(dsn)
    holder.execute(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE")
    return holder


def _table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT to_regclass('public.' || %s) IS NOT NULL AS present", (name,)
    ).fetchone()
    # The bare psycopg.connect in this module has no row factory; accept both.
    return bool(row["present"] if isinstance(row, dict) else row[0])


def test_lock_timeout_does_not_mark_ready(fresh_db, rapid_lock_timeout):
    """A timed-out bootstrap must not claim the schema exists."""
    key = fresh_db.info.dbname
    # Create just one table so there is something to lock, then lock it and run
    # the bootstrapper: its very first DDL statement will block on this.
    fresh_db.execute("CREATE TABLE IF NOT EXISTS eval_runs (id int)")
    fresh_db.commit()
    dsn = fresh_db.info.dsn
    holder = _hold_lock_on(dsn, "eval_runs")
    try:
        ensure_schema(fresh_db)
        assert key not in store_mod._ensured_dbs, (
            "a lock-timeout bootstrap marked the DB ready — later writes will "
            "fail with UndefinedTable and nothing will retry"
        )
        assert not _table_exists(fresh_db, "review_tasks"), (
            "the schema cannot be complete if the DDL never ran; if this table "
            "exists something else built it and this test is not testing the lock path"
        )
    finally:
        holder.rollback()
        holder.close()


def test_retry_after_the_lock_is_released_completes(fresh_db, rapid_lock_timeout):
    """The failure must be transient, not a permanent "already done" lie.

    The stub table exists only to give the lock something to bite on; it is
    dropped before the retry so the second attempt builds the real one (a stub
    ``eval_runs (id int)`` has no unique key, and the FK from
    ``eval_criteria_results`` would fail for a reason unrelated to locks).
    """
    key = fresh_db.info.dbname
    fresh_db.execute("CREATE TABLE IF NOT EXISTS eval_runs (id int)")
    fresh_db.commit()
    holder = _hold_lock_on(fresh_db.info.dsn, "eval_runs")
    try:
        ensure_schema(fresh_db)
    finally:
        holder.rollback()
        holder.close()

    assert key not in store_mod._ensured_dbs
    assert not _table_exists(fresh_db, "review_tasks")

    fresh_db.execute("DROP TABLE eval_runs")
    fresh_db.commit()
    ensure_schema(fresh_db)  # lock gone: this attempt must actually build
    assert key in store_mod._ensured_dbs
    assert _table_exists(fresh_db, "review_tasks")


def test_concurrent_winner_is_recognised(fresh_db, rapid_lock_timeout):
    """The other half: if the tables DO all exist, a timed-out attempt marks ready.

    Distinguishing these two cases is the whole point — the old code treated
    "lock timed out" as "the other process finished", which is only one of the
    two possibilities.
    """
    key = fresh_db.info.dbname
    # Fully bootstrap through a separate path so every required table exists.
    store_mod._ensured_dbs.discard(key)
    ensure_schema(fresh_db)
    store_mod._ensured_dbs.discard(key)  # pretend this process never ran it

    fresh_db.execute("CREATE TABLE IF NOT EXISTS _lock_anchor (id int)")
    fresh_db.commit()
    holder = _hold_lock_on(fresh_db.info.dsn, "eval_runs")
    try:
        # DDL will still time out on eval_runs, but the readiness probe sees
        # every required table present, so "ready" is the honest answer.
        ensure_schema(fresh_db)
        assert key in store_mod._ensured_dbs
    finally:
        holder.rollback()
        holder.close()


def test_missing_required_table_blocks_ready(fresh_db, rapid_lock_timeout):
    """Readiness is asserted by measurement, not by "no exception was raised"."""
    key = fresh_db.info.dbname
    ensure_schema(fresh_db)
    assert key in store_mod._ensured_dbs
    # Drop one required table, evict the cache, and re-ensure: the probe must
    # notice, rebuild it, and only then mark ready.
    fresh_db.execute("DROP TABLE review_tasks CASCADE")
    fresh_db.commit()
    store_mod._ensured_dbs.discard(key)
    assert not _table_exists(fresh_db, "review_tasks")

    ensure_schema(fresh_db)
    assert _table_exists(fresh_db, "review_tasks")
    assert key in store_mod._ensured_dbs


# --- the cached connection must follow the DSN -----------------------------


def test_shared_connection_follows_a_dsn_change(monkeypatch):
    """A process that switches ``database_url`` must not keep writing to the old DB.

    Measured before the fix: two ``ensure_schema()`` calls against two different
    databases both ran their DDL inside the FIRST one, so the second was left
    with no tables and every later call failed with ``UndefinedTable``.
    """
    from urllib.parse import urlparse, urlunparse

    from src.eval import db as edb
    from src.eval.store import ensure_schema as _ensure

    base = edb._dsn()
    parsed = urlparse(base)
    names = ["lb_dsn_probe_a", "lb_dsn_probe_b"]
    with psycopg.connect(base, autocommit=True) as maint:
        for n in names:
            maint.execute(f"DROP DATABASE IF EXISTS {n}")
            maint.execute(f"CREATE DATABASE {n}")
    try:
        for n in names:
            # Deliberately NOT calling close_shared_conn(): that is exactly the
            # situation the conftest fixtures create (they change database_url
            # per test and rely on the cache noticing), and closing it by hand
            # would hide the defect this test exists for.
            monkeypatch.setenv("database_url", urlunparse(parsed._replace(path=f"/{n}")))
            store_mod._ensured_dbs.discard(n)
            _ensure()
            assert n in store_mod._ensured_dbs, f"{n} was never bootstrapped"

            probe = psycopg.connect(urlunparse(parsed._replace(path=f"/{n}")))
            try:
                assert _table_exists(probe, "review_tasks"), (
                    f"ensure_schema wrote its DDL into the wrong database "
                    f"(shared connection was not DSN-aware); {n} has no tables"
                )
            finally:
                probe.close()
    finally:
        edb.close_shared_conn()
        with psycopg.connect(base, autocommit=True) as maint:
            for n in names:
                maint.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s",
                    (n,),
                )
                maint.execute(f"DROP DATABASE IF EXISTS {n}")


def test_bootstrap_repairs_a_table_missing_its_primary_key(fresh_db, rapid_lock_timeout):
    """The production ``eval_runs`` has no PK; the bootstrapper must repair it.

    Measured on the live pod 2026-11-18: ``pg_constraint`` for ``eval_runs`` was
    empty. ``CREATE TABLE IF NOT EXISTS`` can never add a PK to an existing
    table, so the omission survived every deploy — until a process first created
    a table declaring ``REFERENCES eval_runs(id)``, at which point boot died with
    ``InvalidForeignKey`` (CrashLoopBackOff). The repair runs BEFORE those
    creates, so both the references and our new column work.
    """
    key = fresh_db.info.dbname
    # Mimic production: the table exists, with data, and has no PK/unique key.
    fresh_db.execute("CREATE TABLE eval_runs (id bigint, rubric_name text, all_pass integer)")
    fresh_db.execute("INSERT INTO eval_runs VALUES (1, 'legacy', 1)")
    fresh_db.commit()

    store_mod._ensured_dbs.discard(key)
    ensure_schema(fresh_db)  # must not raise

    cols = {
        r["column_name"]
        for r in fresh_db.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'eval_runs'"
        ).fetchall()
    }
    assert "baseline_run_id" in cols
    assert "outcome" in cols
    # The repair is the point: without it the FK-bearing CREATEs above cannot run.
    pk = fresh_db.execute(
        "SELECT contype FROM pg_constraint "
        "WHERE conrelid = 'eval_runs'::regclass AND contype = 'p'"
    ).fetchall()
    assert pk, "the bootstrapper must have added the missing primary key"
