"""Shared pytest fixtures for the chinese-contract-drafter test suite.

Fixtures:
- seeded_db : a live connection to a shared session PostgreSQL DB, reset
  (TRUNCATE ... RESTART IDENTITY) and reseeded with one harbor and one local
  rubric before each test. ``database_url`` is monkeypatched to this DB so code
  that opens its own connection also hits it.
- empty_db : a fresh per-test PostgreSQL DB with no schema (for tests that
  exercise schema creation / harbor self-heal from a clean slate).
- app_client : a FastAPI TestClient whose ``get_db`` dependency is overridden to
  the ``seeded_db`` connection, so web tests never touch the dev database.
- fake_judge : a factory building a deterministic offline ``FakeJudge``.

Hermetic: requires a reachable local PostgreSQL (maintenance DSN derived from
``database_url``) but no Elasticsearch, MinIO, OpenRouter, or LLM endpoint.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest
from dotenv import load_dotenv
from fastapi import Request
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

load_dotenv()
# Legal contract text must not leave the machine; opt out of deepeval telemetry
# for the whole suite (src/eval/run.py sets the same at runtime).
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "true")
# Constructing CrewAI/LiteLLM LLMs otherwise triggers a remote model-cost-map
# fetch; point it at an empty URL so it fails fast and falls back to the local
# copy (keeps the suite hermetic and network-free).
os.environ.setdefault("LITELLM_MODEL_COST_MAP_URL", "")

# Auth env for the test session. Dummy values so create_app()'s fail-closed
# startup check_auth_config() passes and the src.settings module constants
# bind non-empty. logto.verify_reachable() is monkeypatched per-fixture (see
# app_client) so no real IdP HTTP call is made. setdefault honors any real
# values from .env (a locally-configured Logto is still not hit in tests).
# AUTH_COOKIE_SECURE=0 lets TestClient (http) set/read session cookies.
os.environ.setdefault("LOGTO_ENDPOINT", "http://test-logto.local")
os.environ.setdefault("LOGTO_CLIENT_ID", "test-client-id")
os.environ.setdefault("LOGTO_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("LOGTO_REDIRECT_URI", "http://localhost/auth/callback")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-stable-value")
os.environ.setdefault("AUTH_COOKIE_SECURE", "0")

from src.eval.harbor_seed import create_schema  # noqa: E402
from src.web.app import create_app  # noqa: E402
from src.web.auth import logto  # noqa: E402
from src.web.auth.deps import User, get_current_user  # noqa: E402
from src.web.deps import get_db  # noqa: E402

from _fakes import FakeJudge  # noqa: E402  (tests/ is on sys.path via conftest)

REPO_ROOT = Path(__file__).resolve().parents[1]

# All tables that may hold seed/test rows - truncated between tests for isolation.
# law_catalog.* tables are created during session setup (see _session_db_name).
_ALL_TABLES = (
    "review_tasks",
    "eval_criteria_results",
    "eval_runs",
    "compare_runs",
    "criteria",
    "rubrics",
    "prompts",
    "law_info",
    "clauses",
    "contract_artifacts",
    "generation_jobs",
    "api_keys",
    "law_catalog.laws",
    "law_catalog.aliases",
    "law_catalog.clause_law_refs",
    "law_catalog.clause_article_refs",
    "law_catalog.successor_map",
    "law_catalog.citation_revisions",
)


def _base_dsn() -> str:
    return (
        os.environ.get("database_url")
        or os.environ.get("DATABASE_URL")
        or "postgresql://app:CHANGEME@localhost:5432/law_bench"
    )


def _with_db(dsn: str, db_name: str) -> str:
    p = urlparse(dsn)
    return urlunparse(p._replace(path=f"/{db_name}"))


def _maint_dsn() -> str:
    """DSN for the maintenance DB (used to CREATE / DROP per-test databases)."""
    return _with_db(_base_dsn(), "postgres")


_counter = {"n": 0}


def _new_db_name() -> str:
    _counter["n"] += 1
    return f"law_bench_test_{os.getpid()}_{_counter['n']}"


def _create_db(name: str) -> None:
    conn = psycopg.connect(_maint_dsn())
    conn.autocommit = True
    try:
        conn.execute(f'CREATE DATABASE {name}')
    finally:
        conn.close()


def _drop_db(name: str) -> None:
    conn = psycopg.connect(_maint_dsn())
    conn.autocommit = True
    try:
        conn.execute(f'DROP DATABASE IF EXISTS {name}')
    finally:
        conn.close()


def seed_db(conn) -> None:
    """Reset the schema's tables and seed one harbor + one local rubric on ``conn``.

    Truncate + all inserts run as one multi-statement round trip (criteria use
    subqueries against the just-inserted rubrics) to keep the fixture cheap on
    high-RTT connections.
    """
    now = "2026-01-01T00:00:00+00:00"
    conn.execute(
        "TRUNCATE " + ", ".join(_ALL_TABLES) + " RESTART IDENTITY CASCADE; "
        "INSERT INTO rubrics (name, context, source, source_path, description, created_at) "
        f"VALUES ('h_rubric', 'check', 'harbor:v0.20.0', 'p.toml', 'harbor test', '{now}'); "
        "INSERT INTO rubrics (name, context, source, source_path, description, created_at) "
        f"VALUES ('l_rubric', 'contract', 'local', NULL, 'local test', '{now}'); "
        "INSERT INTO criteria (rubric_id, name, description, guidance, ordinal) "
        "SELECT id, 'h_c1', 'hd', 'hg', 0 FROM rubrics WHERE name = 'h_rubric'; "
        "INSERT INTO criteria (rubric_id, name, description, guidance, ordinal) "
        "SELECT id, 'c1', 'd', 'g', 0 FROM rubrics WHERE name = 'l_rubric'; "
        "INSERT INTO criteria (rubric_id, name, description, guidance, ordinal) "
        "SELECT id, 'c2', 'd', 'g', 1 FROM rubrics WHERE name = 'l_rubric';"
    )
    conn.commit()


@pytest.fixture(scope="session")
def _session_db_name() -> str:
    """A shared session PostgreSQL DB with the real schema, created once.

    ``database_url`` is pointed at this DB for the whole session so any code that
    opens its own connection (``connect()``) defaults to it; per-test fixtures
    (``seeded_db``/``empty_db``) may override it further.
    """
    from src.eval.store import ensure_schema  # local import to avoid heavy import

    name = _new_db_name()
    _create_db(name)
    dsn = _with_db(_base_dsn(), name)
    os.environ["database_url"] = dsn
    conn = psycopg.connect(dsn, row_factory=dict_row)
    try:
        create_schema(conn)  # rubrics / criteria / prompts
        conn.commit()
    finally:
        conn.close()
    ensure_schema()  # eval_runs / eval_criteria_results / compare_runs (opens from env)
    # law_catalog schema (法规目录副本) - created up front so the per-test
    # TRUNCATE of _ALL_TABLES (which includes law_catalog.*) never hits a
    # missing table in a fresh session DB.
    from src.law_catalog.store import ensure_schema as ensure_law_catalog_schema

    ensure_law_catalog_schema()
    # Seed the tag_dims vocabulary (from the manifests) into the session DB and
    # load it into the in-memory TAG_VOCAB, so tag tests see the full vocab.
    # tag_dims is intentionally NOT in _ALL_TABLES - it is read-only reference
    # data, seeded once per session and preserved across per-test truncations.
    from src.clauses.seed_manifest import seed_tag_dims
    from src.clauses.tags import load_vocab_from_db

    seed_tag_dims()
    load_vocab_from_db()
    yield name
    # Close any process-wide cached connection to the session DB so the DROP
    # below isn't blocked by "database is being accessed by other users" (the
    # shared connection opened by load_vocab_from_db / store calls via
    # get_shared_conn leaks across the session otherwise).
    from src.eval.db import close_shared_conn

    close_shared_conn()
    _drop_db(name)


@pytest.fixture
def seeded_db(_session_db_name: str, monkeypatch) -> "psycopg.Connection":
    """A connection to the session DB, reset + reseeded per test."""
    dsn = _with_db(_base_dsn(), _session_db_name)
    monkeypatch.setenv("database_url", dsn)
    conn = psycopg.connect(dsn, row_factory=dict_row)
    seed_db(conn)
    yield conn
    conn.close()


@pytest.fixture
def empty_db(monkeypatch) -> "psycopg.Connection":
    """A fresh per-test Postgres DB with no schema (for self-heal / migration tests)."""
    name = _new_db_name()
    _create_db(name)
    dsn = _with_db(_base_dsn(), name)
    monkeypatch.setenv("database_url", dsn)
    conn = psycopg.connect(dsn, row_factory=dict_row)
    yield conn
    conn.close()
    _drop_db(name)


def _test_user(request: Request) -> User:
    """Stub authenticated user for the non-auth test suite.

    Installed as a dependency_overrides replacement for get_current_user so
    every protected route sees an authenticated caller without per-test
    tokens. Mirrors the real dependency's contract by setting
    ``request.state.user``, which the ``has_scope`` template helper reads to
    render the chrome. Auth behavior itself is exercised in
    tests/test_web_auth.py via a separate fixture that does NOT override
    get_current_user.
    """
    user = User(
        sub="test-user",
        name="Test User",
        email="test@example.com",
        scopes=["*"],
        channel="test",
    )
    request.state.user = user
    return user


@pytest.fixture
def app_client(seeded_db, monkeypatch) -> TestClient:
    """A TestClient whose web routes read/write the throwaway DB.

    Auth is bypassed for the existing suite: logto.verify_reachable is
    neutralized so the fail-closed startup probe doesn't hit a real IdP, and
    get_current_user is overridden to a stub test user so every protected
    route sees an authenticated caller. (Auth-channel behavior — 401 without
    creds, cookie/bearer/apikey paths — is covered by tests/test_web_auth.py
    with a fixture that leaves get_current_user real.)
    """
    monkeypatch.setattr(logto, "verify_reachable", lambda: None)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: seeded_db
    app.dependency_overrides[get_current_user] = _test_user
    with TestClient(app) as client:
        yield client


@pytest.fixture
def fake_judge():
    """Factory building a deterministic offline FakeJudge with given verdicts."""

    def _make(verdicts: list, model_name: str | None = "fake-judge") -> FakeJudge:
        return FakeJudge(verdicts=verdicts, model_name=model_name)

    return _make
