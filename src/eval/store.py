"""Persist evaluation runs to the PostgreSQL database (``database_url``).

Adds two tables alongside the existing rubric-definition tables (rubrics /
criteria, which are never touched here):

  eval_runs             - one row per evaluation run: run-level score,
                         all-pass flag, n_passed/n_criteria diagnostics, etc.
  eval_criteria_results - one row per criterion verdict within a run
                         (criterion_id, title, verdict, reasoning, ordinal)

Both mirror harvey-labs' scores.json structure, but relational so runs can be
queried and compared over time. The schema is created idempotently.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Optional

import psycopg
from psycopg.errors import DeadlockDetected

from src.settings import DEFAULT_DB  # retained as the legacy default param value

from .db import connect


def _retry_on_deadlock(func, max_retries: int = 3, base_delay: float = 0.1):
    """Retry a database operation if it hits a deadlock or connection error.

    PostgreSQL deadlocks can occur when multiple processes run ALTER TABLE
    (via ensure_schema) concurrently with INSERT operations. Connection errors
    (AdminShutdown, OperationalError) can occur when the server terminates idle
    connections during long LLM calls. This wrapper retries with exponential backoff.
    """
    for attempt in range(max_retries + 1):
        try:
            return func()
        except (DeadlockDetected, psycopg.errors.AdminShutdown, psycopg.errors.OperationalError, psycopg.errors.LockNotAvailable, psycopg.errors.InFailedSqlTransaction) as e:
            if attempt == max_retries:
                raise
            # Force close the shared connection to trigger reconnect on retry
            try:
                from src.eval.db import close_shared_conn
                close_shared_conn()
            except Exception:
                pass
            delay = base_delay * (2 ** attempt)
            time.sleep(delay)

RESULTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS eval_runs (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rubric_name    TEXT NOT NULL,
    contract_path  TEXT,
    task_desc      TEXT,
    score          REAL NOT NULL,
    max_score      REAL NOT NULL,
    all_pass       INTEGER NOT NULL,
    n_criteria     INTEGER NOT NULL,
    n_passed       INTEGER NOT NULL,
    summary        TEXT,
    judge_model    TEXT,
    scored_at      TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    compare_run_id INTEGER,
    prompt_name    TEXT,
    prompt_type    TEXT,
    variant_label  TEXT,
    draft_text     TEXT
);

CREATE TABLE IF NOT EXISTS eval_criteria_results (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id       BIGINT NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    criterion_id TEXT NOT NULL,
    title        TEXT,
    verdict      TEXT NOT NULL,
    reasoning    TEXT,
    ordinal      INTEGER NOT NULL,
    UNIQUE(run_id, criterion_id)
);

CREATE TABLE IF NOT EXISTS compare_runs (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    label         TEXT,
    contract_type TEXT,
    rubric_name   TEXT,
    task_desc     TEXT,
    gen_mode      TEXT,
    n_drafts      INTEGER,
    created_at    TEXT NOT NULL
);
"""

# law_info table (per-contract-type 法律法规 survey answers, one row per
# (contract_type, source)). Created here too so the runtime path establishes it
# even if the seeder's create_schema has not run on this database.
LAW_INFO_SCHEMA = """
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

# clauses table (reusable contract clauses extracted from the 示范文本 corpus;
# three categories via the `category` column). Owned by src/clauses, but the DDL
# lives here so ensure_schema establishes it on any database the app touches.
CLAUSES_SCHEMA = """
CREATE TABLE IF NOT EXISTS clauses (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    contract_type    TEXT NOT NULL,
    category         TEXT NOT NULL CHECK (category IN ('base','tagged','custom')),
    section          TEXT NOT NULL,
    body             TEXT NOT NULL,
    slot_instructions JSONB NOT NULL DEFAULT '[]'::jsonb,
    law_refs         JSONB NOT NULL DEFAULT '[]'::jsonb,
    level            TEXT CHECK (level IN ('national','local')),
    source_path      TEXT,
    source_doc_title TEXT,
    body_hash        TEXT NOT NULL,
    manual           BOOLEAN NOT NULL DEFAULT false,
    tags             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS clauses_upsert_uk
    ON clauses (source_path, section, body_hash)
    WHERE source_path IS NOT NULL;
"""

# tag_dims table: the controlled-vocabulary tag dimensions (name -> allowed
# values). Populated once per DB by seed_tag_dims (from the per-type manifests)
# and read into the in-memory TAG_VOCAB at app startup, so the running image
# need not ship the seed files. Owned by src/clauses; DDL lives here so
# ensure_schema establishes it on any database the app touches.
TAG_DIMS_SCHEMA = """
CREATE TABLE IF NOT EXISTS tag_dims (
    name           TEXT NOT NULL,
    contract_type  TEXT,          -- NULL = universal (shared across all types); <key> = type-specific
    category       TEXT,          -- 来源/利益倾向/风险合规/地域/类型专属
    values         JSONB NOT NULL DEFAULT '[]'::jsonb,
    free_form      BOOLEAN NOT NULL DEFAULT false,
    zh_label       TEXT,
    description    TEXT
);
"""

# Pipeline tables (LangGraph generate->fill->evaluate pipeline). One
# pipeline_runs row per pipeline_run call (links to eval_runs via eval_run_id);
# fill_cache memoizes LLM slot-fills so identical inputs are deterministic.
PIPELINE_SCHEMA = """
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    contract_type   TEXT NOT NULL,
    tags            JSONB NOT NULL DEFAULT '{}'::jsonb,
    stance          TEXT,
    rubric_name     TEXT NOT NULL,
    task_desc       TEXT,
    fill_mode       TEXT,
    fill_values     JSONB NOT NULL DEFAULT '{}'::jsonb,
    filled_text     TEXT,
    eval_run_id     BIGINT REFERENCES eval_runs(id) ON DELETE SET NULL,
    score           REAL,
    max_score       REAL,
    n_passed        INTEGER,
    n_criteria      INTEGER,
    all_pass        INTEGER,
    iteration       INTEGER NOT NULL DEFAULT 1,
    actions_taken   JSONB NOT NULL DEFAULT '[]'::jsonb,
    recommendations JSONB NOT NULL DEFAULT '[]'::jsonb,
    fill_cache_id   BIGINT,
    fill_temperature REAL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fill_cache (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cache_key     TEXT NOT NULL UNIQUE,
    contract_type TEXT NOT NULL,
    scenario      TEXT,
    slots_hash    TEXT NOT NULL,
    fill_values   JSONB NOT NULL DEFAULT '{}'::jsonb,
    temperature   REAL,
    model         TEXT,
    created_at    TEXT NOT NULL
);
"""

# Industry standard reference tables for contract evaluation rubric refactoring.
# industry_standard_references maps contract types to their governing statutes;
# core_clauses defines the essential mandatory clauses for each contract type.
INDUSTRY_STANDARD_SCHEMA = """
CREATE TABLE IF NOT EXISTS industry_standard_references (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    contract_type       TEXT NOT NULL UNIQUE,
    governing_statutes  TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS core_clauses (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    contract_type           TEXT NOT NULL UNIQUE REFERENCES industry_standard_references(contract_type) ON DELETE CASCADE,
    core_mandatory_clauses  JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
);
"""

# API evaluation runs (async REST API for contract evaluation). Separate from
# eval_runs because the lifecycle is different: pending -> running -> completed/
# failed, with the full contract text stored inline for self-contained records.
API_EVAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_eval_runs (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rubric_name     TEXT NOT NULL,
    contract_text   TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    score           REAL,
    all_pass        BOOLEAN,
    n_passed        INTEGER,
    n_criteria      INTEGER,
    results         JSONB,
    error_message   TEXT,
    judge_model     TEXT,
    created_at      TEXT NOT NULL,
    completed_at    TEXT
);
"""

# Generation jobs (async REST API for the contract-detail "生成合同模板" panel).
# One row per long-running generation run for modes D/E/F/G. The `kind` column
# discriminates the mode ('batch' | 'pipeline' | 'auto_reject' | 'regenerate');
# `result_ref` is a JSON-text pointer to the mode's real output
# (e.g. {"pipeline_run_id": 42} for E/F, {"files": [...]} for D/G) so the
# panel's poller is one shape regardless of mode. Mirrors the api_eval_runs
# pending -> running -> completed/failed status machine.
GENERATION_JOBS_SCHEMA = """
CREATE TABLE IF NOT EXISTS generation_jobs (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind            TEXT NOT NULL CHECK (kind IN ('batch','pipeline','auto_reject','regenerate')),
    contract_type   TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','running','completed','failed')),
    result_ref      TEXT,
    error_message   TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
"""

# Generated contract docx/pdf artifacts (uploaded to MinIO, content-addressed
# by body_hash so identical inputs reuse the same artifact). One row per
# distinct assembled body; docx_key/pdf_key are nullable per-format MinIO keys.
CONTRACT_ARTIFACTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS contract_artifacts (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    contract_type       TEXT NOT NULL,
    scenario            TEXT,
    stance              TEXT,
    custom_clause_ids   JSONB,
    body_hash           TEXT NOT NULL UNIQUE,
    body_text           TEXT NOT NULL,
    slots               JSONB NOT NULL DEFAULT '[]'::jsonb,
    docx_key            TEXT,
    pdf_key             TEXT,
    docx_key_slotted    TEXT,
    pdf_key_slotted     TEXT,
    minio_bucket        TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    superseded_at       TEXT
);
"""


# Additive columns added after the tables' first release, applied idempotically
# in a single round trip via ``ALTER TABLE IF EXISTS ... ADD COLUMN IF NOT
# EXISTS`` (a no-op once the columns exist; safe when the table is absent).
_ADDITIVE_COLUMNS = (
    "ALTER TABLE IF EXISTS prompts ADD COLUMN IF NOT EXISTS prompt_type TEXT; "
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS compare_run_id INTEGER; "
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS prompt_name TEXT; "
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS prompt_type TEXT; "
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS variant_label TEXT; "
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS draft_text TEXT; "
    "ALTER TABLE IF EXISTS clauses ADD COLUMN IF NOT EXISTS manual BOOLEAN NOT NULL DEFAULT false; "
    "ALTER TABLE IF EXISTS clauses ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '{}'::jsonb; "
    "ALTER TABLE IF EXISTS clauses DROP COLUMN IF EXISTS province; "
    "ALTER TABLE IF EXISTS clauses DROP COLUMN IF EXISTS category; "
    "ALTER TABLE IF EXISTS clauses DROP COLUMN IF EXISTS level; "
    "ALTER TABLE IF EXISTS clauses ADD COLUMN IF NOT EXISTS tag_review JSONB NOT NULL DEFAULT '{}'::jsonb; "
    "ALTER TABLE IF EXISTS tag_dims ADD COLUMN IF NOT EXISTS contract_type TEXT; "
    "ALTER TABLE IF EXISTS tag_dims ADD COLUMN IF NOT EXISTS category TEXT; "
    "ALTER TABLE IF EXISTS tag_dims ADD COLUMN IF NOT EXISTS free_form BOOLEAN NOT NULL DEFAULT false; "
    "ALTER TABLE IF EXISTS tag_dims ADD COLUMN IF NOT EXISTS zh_label TEXT; "
    "ALTER TABLE IF EXISTS tag_dims ADD COLUMN IF NOT EXISTS description TEXT; "
    "CREATE UNIQUE INDEX IF NOT EXISTS tag_dims_name_uk ON tag_dims (name) WHERE contract_type IS NULL; "
    "CREATE UNIQUE INDEX IF NOT EXISTS tag_dims_type_name_uk ON tag_dims (contract_type, name) WHERE contract_type IS NOT NULL; "
    # region (province) tag retired in favor of scenario (业务场景): drop the
    # JSONB keys from existing rows. Idempotent (no-op once the keys are gone).
    "UPDATE clauses SET tags = tags - 'region' WHERE tags ? 'region'; "
    "UPDATE clauses SET tag_review = tag_review - 'region' WHERE tag_review ? 'region'; "
    # learn_applied: clauses auto-rejected by the learn node (auto-iteration pipeline)
    "ALTER TABLE IF EXISTS pipeline_runs ADD COLUMN IF NOT EXISTS learn_applied JSONB NOT NULL DEFAULT '[]'::jsonb; "
    # Dual-variant artifact storage: slotted (fillable {{slot}}) keys alongside
    # the final (underline-blank) keys. Nullable; backfilled on next --force.
    "ALTER TABLE IF EXISTS contract_artifacts ADD COLUMN IF NOT EXISTS docx_key_slotted TEXT; "
    "ALTER TABLE IF EXISTS contract_artifacts ADD COLUMN IF NOT EXISTS pdf_key_slotted TEXT; "
    # Soft-delete marker for superseded artifact versions: when generate_stored
    # inserts a new body for an existing natural key (contract_type, scenario,
    # stance, custom_clause_ids), the old row is stamped superseded_at = now_iso()
    # so /samples hides it by default. NULL = current version. TEXT (not TIMESTAMPTZ)
    # to match created_at/updated_at. Safe no-op on fresh DBs (CREATE TABLE added it).
    "ALTER TABLE IF EXISTS contract_artifacts ADD COLUMN IF NOT EXISTS superseded_at TEXT;"
)

# Self-managed long-lived API keys (Phase 2 auth). The plaintext key is never
# persisted or logged. The key is ``lbk_<43urlsafe>``; we split it into a public
# ``key_prefix`` (first 16 chars) used for O(1) indexed lookup, and a salted
# slow-hash (``key_hash``, pbkdf2-hmac-sha256) verified *after* the lookup. The
# UNIQUE index therefore lives on ``key_prefix`` (not ``key_hash`` — a salted
# hash is non-deterministic and cannot be indexed by the incoming plaintext).
# ``revoked_at`` soft-deletes a key so the row survives for audit without being
# usable. Owned by src/web/auth, but the DDL lives here so ensure_schema
# establishes it on any database the app touches — same convention as clauses /
# tag_dims.
API_KEYS_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key_prefix   TEXT NOT NULL UNIQUE,
    key_hash     TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    label        TEXT NOT NULL,
    scopes       JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at   TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at   TEXT
);
"""


# Human-review annotation slots on eval verdicts (change add-web-human-review).
# One row = one annotator slot on one eval_criteria_results row within a batch;
# double annotation is two slot rows, not two columns. `annotator` is stamped
# from the authenticated web session (never a free-text form field) and stays
# NULL until a decision lands. Owned by src/eval/review, but the DDL lives here
# so ensure_schema establishes it on any database the app touches — same
# convention as api_keys.
REVIEW_TASKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS review_tasks (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id                TEXT NOT NULL,
    batch_type              TEXT NOT NULL,
    eval_criteria_result_id BIGINT NOT NULL REFERENCES eval_criteria_results(id) ON DELETE CASCADE,
    slot                    INTEGER NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'pending',
    annotator_verdict       TEXT,
    annotator               TEXT,
    note                    TEXT,
    reviewed_at             TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (batch_id, eval_criteria_result_id, slot)
);
CREATE INDEX IF NOT EXISTS review_tasks_batch_idx ON review_tasks (batch_id, status);
"""


# The DDL is fully idempotent, so ensure_schema is memoized per database (keyed
# by dbname): the first call on a given DB creates/migrates; subsequent calls
# (every store/list/compare) are a cheap no-op. This matters because the store
# functions call ensure_schema defensively on every invocation.
_ensured_dbs: set[str] = set()
_ensure_lock = threading.Lock()


def ensure_schema(db_path=DEFAULT_DB) -> None:
    """Create the results/compare tables if missing and migrate additive columns.

    Idempotent: ``CREATE TABLE IF NOT EXISTS`` for fresh tables, plus
    ``ALTER TABLE IF EXISTS ... ADD COLUMN IF NOT EXISTS`` for columns added
    after the tables' first release (a no-op once the columns exist). Memoized
    per database so repeated calls are cheap.
    """
    def _do_ensure():
        conn = connect(db_path)
        try:
            key = getattr(getattr(conn, "info", None), "dbname", None) or str(db_path)
            if key in _ensured_dbs:
                return
            # Set a short lock timeout so DDL doesn't deadlock with concurrent
            # processes; the DDL is idempotent so skipping on lock timeout is safe.
            conn.execute("SET lock_timeout = '3s'")
            conn.execute(RESULTS_SCHEMA)
            conn.execute(LAW_INFO_SCHEMA)
            conn.execute(CLAUSES_SCHEMA)
            conn.execute(TAG_DIMS_SCHEMA)
            conn.execute(PIPELINE_SCHEMA)
            conn.execute(INDUSTRY_STANDARD_SCHEMA)
            conn.execute(CONTRACT_ARTIFACTS_SCHEMA)
            conn.execute(API_EVAL_SCHEMA)
            conn.execute(GENERATION_JOBS_SCHEMA)
            conn.execute(API_KEYS_SCHEMA)
            conn.execute(REVIEW_TASKS_SCHEMA)
            conn.execute(_ADDITIVE_COLUMNS)
            conn.commit()
            _ensured_dbs.add(key)
        except psycopg.errors.LockNotAvailable:
            # Another process holds the lock; schema should already exist from
            # previous runs, so just mark as ensured and continue.
            _ensured_dbs.add(key)
        finally:
            conn.close()
    with _ensure_lock:
        _retry_on_deadlock(_do_ensure)


def store_result(
    result: dict,
    contract_path: Optional[str] = None,
    task_desc: Optional[str] = None,
    db_path=DEFAULT_DB,
    *,
    compare_run_id: Optional[int] = None,
    prompt_name: Optional[str] = None,
    prompt_type: Optional[str] = None,
    variant_label: Optional[str] = None,
    draft_text: Optional[str] = None,
) -> int:
    """Insert an evaluation run + its per-criterion verdicts. Returns the run id.

    The rubric/contract/task_desc are snapshotted as text so a run survives later
    edits or deletion of the rubric it used. Compare-driven columns
    (``compare_run_id``, ``prompt_name``, ``prompt_type``, ``variant_label``,
    ``draft_text``) are optional keyword-only args; standalone runs leave them
    null, compare runs populate them so the run is grouped under and traceable
    to its prompt without a foreign key.
    """
    ensure_schema(db_path)
    now = datetime.now(timezone.utc).isoformat()

    def _do_insert():
        conn = connect(db_path)
        try:
            cur = conn.execute(
                "INSERT INTO eval_runs "
                "(rubric_name, contract_path, task_desc, score, max_score, all_pass, "
                " n_criteria, n_passed, summary, judge_model, scored_at, created_at, "
                " compare_run_id, prompt_name, prompt_type, variant_label, draft_text) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (
                    result["rubric"],
                    contract_path,
                    task_desc,
                    result["score"],
                    result["max_score"],
                    int(result["all_pass"]),
                    result["n_criteria"],
                    result["n_passed"],
                    result.get("summary"),
                    result.get("judge_model"),
                    result.get("scored_at") or now,
                    now,
                    compare_run_id,
                    prompt_name,
                    prompt_type,
                    variant_label,
                    draft_text,
                ),
            )
            run_id = cur.fetchone()["id"]

            for i, c in enumerate(result.get("criteria_results", [])):
                conn.execute(
                    "INSERT INTO eval_criteria_results "
                    "(run_id, criterion_id, title, verdict, reasoning, ordinal) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    (run_id, c["id"], c.get("title"), c["verdict"], c.get("reasoning", ""), i),
                )
            conn.commit()
            return run_id
        finally:
            conn.close()

    return _retry_on_deadlock(_do_insert)


def _retry_db_operation(func, max_retries: int = 3, base_delay: float = 0.1):
    """Retry a database operation if it hits a deadlock."""
    for attempt in range(max_retries + 1):
        try:
            return func()
        except DeadlockDetected:
            if attempt == max_retries:
                raise
            delay = base_delay * (2 ** attempt)
            time.sleep(delay)


def list_runs(limit: int = 20, db_path=DEFAULT_DB) -> list[dict]:
    """Recent runs (run-level fields only) for quick inspection."""
    def _do_list():
        conn = connect(db_path)
        try:
            rows = conn.execute(
                "SELECT id, rubric_name, contract_path, score, all_pass, "
                "       n_passed, n_criteria, judge_model, scored_at "
                "FROM eval_runs ORDER BY id DESC LIMIT %s",
                (limit,),
            ).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]
    return _retry_db_operation(_do_list)


def get_run(run_id: int, db_path=DEFAULT_DB) -> dict:
    """A single run's run-level fields plus its ordered per-criterion verdicts.

    The counterpart to :func:`list_runs` (which returns run-level fields only):
    use this to fetch one run's full ``criteria_results``. Raises ``KeyError`` if
    no run has ``id == run_id``.
    """
    def _do_get():
        conn = connect(db_path)
        try:
            row = conn.execute(
                "SELECT id, rubric_name, contract_path, task_desc, score, max_score, "
                "       all_pass, n_criteria, n_passed, summary, judge_model, "
                "       scored_at, compare_run_id, prompt_name, prompt_type, variant_label "
                "FROM eval_runs WHERE id = %s",
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Run not found: {run_id}")
            crits = conn.execute(
                "SELECT criterion_id, title, verdict, reasoning, ordinal "
                "FROM eval_criteria_results WHERE run_id = %s ORDER BY ordinal",
                (run_id,),
            ).fetchall()
        finally:
            conn.close()
        return {**dict(row), "criteria_results": [dict(c) for c in crits]}
    return _retry_db_operation(_do_get)


# --- compare runs ---------------------------------------------------------- #


def store_compare(
    label: Optional[str],
    contract_type: str,
    rubric_name: str,
    task_desc: Optional[str],
    gen_mode: str,
    n_drafts: int,
    db_path=DEFAULT_DB,
) -> int:
    """Insert a ``compare_runs`` row and return its id.

    The returned id is the grouping key passed back as ``compare_run_id`` when
    storing each ``eval_runs`` row that belongs to this compare.
    """
    ensure_schema(db_path)
    now = datetime.now(timezone.utc).isoformat()
    conn = connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO compare_runs "
            "(label, contract_type, rubric_name, task_desc, gen_mode, n_drafts, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (label, contract_type, rubric_name, task_desc, gen_mode, n_drafts, now),
        )
        conn.commit()
        return cur.fetchone()["id"]
    finally:
        conn.close()


def list_compares(limit: int = 20, db_path=DEFAULT_DB) -> list[dict]:
    """Recent compares (compare-level fields only) for the listing view."""
    ensure_schema(db_path)
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, label, contract_type, rubric_name, task_desc, gen_mode, "
            "       n_drafts, created_at "
            "FROM compare_runs ORDER BY id DESC LIMIT %s",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_compare(compare_id: int, db_path=DEFAULT_DB) -> dict:
    """Full grouped result for one compare: the ``compare_runs`` row, its
    ``eval_runs`` (each with per-criterion verdicts), snapshotted prompt metadata.

    ``draft_text`` is intentionally excluded - it is bulky and fetched lazily via
    ``get_run_draft`` so the default compare payload stays compact.
    """
    ensure_schema(db_path)
    conn = connect(db_path)
    try:
        cr = conn.execute(
            "SELECT id, label, contract_type, rubric_name, task_desc, gen_mode, "
            "       n_drafts, created_at FROM compare_runs WHERE id = %s",
            (compare_id,),
        ).fetchone()
        if cr is None:
            raise KeyError(f"Compare not found: {compare_id}")
        runs = conn.execute(
            "SELECT id, rubric_name, contract_path, task_desc, score, max_score, "
            "       all_pass, n_criteria, n_passed, summary, judge_model, scored_at, "
            "       compare_run_id, prompt_name, prompt_type, variant_label "
            "FROM eval_runs WHERE compare_run_id = %s ORDER BY id",
            (compare_id,),
        ).fetchall()
        runs_out = []
        for r in runs:
            crits = conn.execute(
                "SELECT criterion_id, title, verdict, reasoning, ordinal "
                "FROM eval_criteria_results WHERE run_id = %s ORDER BY ordinal",
                (r["id"],),
            ).fetchall()
            runs_out.append({**dict(r), "criteria_results": [dict(c) for c in crits]})
    finally:
        conn.close()
    return {
        "id": cr["id"],
        "label": cr["label"],
        "contract_type": cr["contract_type"],
        "rubric_name": cr["rubric_name"],
        "task_desc": cr["task_desc"],
        "gen_mode": cr["gen_mode"],
        "n_drafts": cr["n_drafts"],
        "created_at": cr["created_at"],
        "runs": runs_out,
    }


def get_run_draft(compare_id: int, run_id: int, db_path=DEFAULT_DB) -> dict:
    """Lazy-fetch a single run's ``draft_text`` (verified to belong to the compare)."""
    ensure_schema(db_path)
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, compare_run_id, prompt_name, draft_text FROM eval_runs WHERE id = %s",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise KeyError(f"Run not found: {run_id}")
    if row["compare_run_id"] != compare_id:
        raise KeyError(f"Run {run_id} does not belong to compare {compare_id}")
    return {
        "run_id": row["id"],
        "prompt_name": row["prompt_name"],
        "draft_text": row["draft_text"],
    }


# --- api eval runs --------------------------------------------------------- #


def store_api_eval_run(
    rubric_name: str,
    contract_text: str,
    db_path=DEFAULT_DB,
) -> int:
    """Insert a new api_eval_runs row with status='pending'. Returns run_id."""
    ensure_schema(db_path)
    now = datetime.now(timezone.utc).isoformat()

    def _do_insert():
        conn = connect(db_path)
        try:
            cur = conn.execute(
                "INSERT INTO api_eval_runs (rubric_name, contract_text, status, created_at) "
                "VALUES (%s, %s, 'pending', %s) RETURNING id",
                (rubric_name, contract_text, now),
            )
            conn.commit()
            return cur.fetchone()["id"]
        finally:
            conn.close()

    return _retry_on_deadlock(_do_insert)


def update_api_eval_run(
    run_id: int,
    *,
    status: str,
    score: Optional[float] = None,
    all_pass: Optional[bool] = None,
    n_passed: Optional[int] = None,
    n_criteria: Optional[int] = None,
    results: Optional[dict] = None,
    error_message: Optional[str] = None,
    judge_model: Optional[str] = None,
    db_path=DEFAULT_DB,
) -> None:
    """Update an api_eval_runs row's status and results."""
    import json

    now = datetime.now(timezone.utc).isoformat()

    def _do_update():
        conn = connect(db_path)
        try:
            conn.execute(
                "UPDATE api_eval_runs SET status=%s, score=%s, all_pass=%s, "
                "n_passed=%s, n_criteria=%s, results=%s, error_message=%s, "
                "judge_model=%s, completed_at=%s WHERE id=%s",
                (
                    status, score, all_pass, n_passed, n_criteria,
                    json.dumps(results) if results else None,
                    error_message, judge_model, now, run_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    _retry_on_deadlock(_do_update)


def get_api_eval_run(run_id: int, db_path=DEFAULT_DB) -> dict:
    """Fetch a single api_eval_run by id. Raises KeyError if not found."""
    ensure_schema(db_path)

    def _do_get():
        conn = connect(db_path)
        try:
            row = conn.execute(
                "SELECT id, rubric_name, contract_text, status, score, all_pass, "
                "       n_passed, n_criteria, results, error_message, judge_model, "
                "       created_at, completed_at "
                "FROM api_eval_runs WHERE id = %s",
                (run_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise KeyError(f"API eval run not found: {run_id}")
        return dict(row)

    return _retry_db_operation(_do_get)


def list_api_eval_runs(limit: int = 20, db_path=DEFAULT_DB) -> list[dict]:
    """Recent API eval runs (most recent first)."""
    ensure_schema(db_path)

    def _do_list():
        conn = connect(db_path)
        try:
            rows = conn.execute(
                "SELECT id, rubric_name, status, score, all_pass, n_passed, "
                "       n_criteria, error_message, judge_model, created_at, completed_at "
                "FROM api_eval_runs ORDER BY id DESC LIMIT %s",
                (limit,),
            ).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    return _retry_db_operation(_do_list)


# --- generation jobs ------------------------------------------------------- #


def store_generation_job(
    kind: str,
    contract_type: str,
    db_path=DEFAULT_DB,
) -> int:
    """Insert a new ``generation_jobs`` row with ``status='pending'``.

    ``kind`` discriminates the mode
    (``'batch' | 'pipeline' | 'auto_reject' | 'regenerate'``). Returns the new
    job id (the value the panel polls via ``GET /api/generation-jobs/{id}``).
    """
    ensure_schema(db_path)
    now = datetime.now(timezone.utc).isoformat()

    def _do_insert():
        conn = connect(db_path)
        try:
            cur = conn.execute(
                "INSERT INTO generation_jobs (kind, contract_type, status, created_at, updated_at) "
                "VALUES (%s, %s, 'pending', %s, %s) RETURNING id",
                (kind, contract_type, now, now),
            )
            conn.commit()
            return cur.fetchone()["id"]
        finally:
            conn.close()

    return _retry_on_deadlock(_do_insert)


def update_generation_job(
    job_id: int,
    *,
    status: str,
    result_ref: Optional[dict] = None,
    error_message: Optional[str] = None,
    db_path=DEFAULT_DB,
) -> None:
    """Update a ``generation_jobs`` row's status and result/error.

    ``result_ref`` is a dict pointer to the mode's real output (e.g.
    ``{"pipeline_run_id": 42}``); it is JSON-encoded for storage. Only the
    fields passed are written; the row's ``updated_at`` is always refreshed.
    """
    import json

    now = datetime.now(timezone.utc).isoformat()

    def _do_update():
        conn = connect(db_path)
        try:
            conn.execute(
                "UPDATE generation_jobs SET status=%s, result_ref=%s, "
                "error_message=%s, updated_at=%s WHERE id=%s",
                (
                    status,
                    json.dumps(result_ref, ensure_ascii=False) if result_ref else None,
                    error_message,
                    now,
                    job_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    _retry_on_deadlock(_do_update)


def get_generation_job(job_id: int, db_path=DEFAULT_DB) -> Optional[dict]:
    """Fetch a single ``generation_jobs`` row by id, or ``None`` if absent."""
    ensure_schema(db_path)

    def _do_get():
        conn = connect(db_path)
        try:
            row = conn.execute(
                "SELECT id, kind, contract_type, status, result_ref, "
                "       error_message, created_at, updated_at "
                "FROM generation_jobs WHERE id = %s",
                (job_id,),
            ).fetchone()
        finally:
            conn.close()
        return dict(row) if row is not None else None

    return _retry_db_operation(_do_get)


def list_generation_jobs(limit: int = 20, db_path=DEFAULT_DB) -> list[dict]:
    """Recent generation jobs (most recent first)."""
    ensure_schema(db_path)

    def _do_list():
        conn = connect(db_path)
        try:
            rows = conn.execute(
                "SELECT id, kind, contract_type, status, result_ref, "
                "       error_message, created_at, updated_at "
                "FROM generation_jobs ORDER BY id DESC LIMIT %s",
                (limit,),
            ).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    return _retry_db_operation(_do_list)
