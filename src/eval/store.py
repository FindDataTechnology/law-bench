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

import logging
import os
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
# Primary keys the production databases are missing (measured live 2026-11-18).
# ``CREATE TABLE IF NOT EXISTS`` cannot add a PK to a table that already exists,
# so the omission survived every deploy — until a process first created a table
# with ``REFERENCES <that table>(id)``, at which point the boot crashed with
# ``InvalidForeignKey: no unique constraint matching given keys``. Running this
# first makes those references legal.
#
# Guarded so it is a no-op once the key exists, and so it fails loudly rather
# than silently skipping when the data cannot support it (duplicate / NULL ids —
# in that case a human must reconcile the rows; a PK cannot be conjured).
_PK_REPAIRS = """
DO $$
BEGIN
    -- Two steps, not one AND: Postgres does not promise left-to-right
    -- short-circuit for AND, so 'eval_runs'::regclass would still be evaluated on
    -- a fresh database (where the CREATEs below have not run yet) and raise.
    IF to_regclass('public.eval_runs') IS NOT NULL THEN
      IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'eval_runs'::regclass AND contype = 'p'
      ) THEN
        ALTER TABLE eval_runs ADD CONSTRAINT eval_runs_pkey PRIMARY KEY (id);
      END IF;
    END IF;
END $$;
"""

_ADDITIVE_COLUMNS = (
    "ALTER TABLE IF EXISTS prompts ADD COLUMN IF NOT EXISTS prompt_type TEXT; "
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS compare_run_id INTEGER; "
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS prompt_name TEXT; "
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS prompt_type TEXT; "
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS variant_label TEXT; "
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS draft_text TEXT; "
    # knowledge-bench kernel (add-knowledge-bench-platform): every run is
    # honestly labeled with its channel (text judge vs deterministic data
    # checks) and the unit kind it evaluated. Defaults keep every legacy row
    # and every legacy insert path reading exactly as before.
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'text'; "
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS unit_kind TEXT NOT NULL DEFAULT 'clause'; "
    # eval-verdict-ledger: every run names WHAT was evaluated (subject), WITH
    # WHICH ruler (ruler + its canonical digest), under which gate, and what
    # came out (outcome: pass/fail/inconclusive). All nullable: a legacy row
    # that predates the ledger reads exactly as before, and a caller that
    # passes none of the new args writes exactly the row it wrote yesterday.
    # ``baseline_run_id`` is a plain column (no FK) — see the note at the ALTER
    # below for why a self-reference is impossible on the production table.
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS subject_kind TEXT; "
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS subject_key TEXT; "
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS subject_version TEXT; "
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS ruler_kind TEXT; "
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS ruler_key TEXT; "
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS ruler_digest TEXT; "
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS gate TEXT; "
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS outcome TEXT; "
    # The production table predates the IDENTITY-PK DDL and has no primary key
    # (measured 2026-11-18 on the live pod: zero rows in pg_constraint). That is
    # repaired by _PK_REPAIRS before this block runs, which is what lets this FK
    # — and every ``REFERENCES eval_runs(id)`` in the CREATE blocks above — exist
    # at all. Without the repair, a fresh process crashes at boot with
    # ``InvalidForeignKey: no unique constraint matching given keys``.
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS baseline_run_id BIGINT "
    "  REFERENCES eval_runs(id) ON DELETE SET NULL; "
    "ALTER TABLE IF EXISTS eval_runs ADD COLUMN IF NOT EXISTS provisional BOOLEAN NOT NULL DEFAULT false; "
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
    # Content fingerprints (lex-matter-spine 5.3): sha256 of the **stored file
    # bytes**, so a downloader can verify what it got and a case artifact can
    # anchor the e-signature to the exact file. body_hash (md5 of the body) can
    # never prove that: same body + different render = different bytes. Nullable;
    # filled on the next render, legacy rows honestly read as unknown.
    "ALTER TABLE IF EXISTS contract_artifacts ADD COLUMN IF NOT EXISTS docx_sha256 TEXT; "
    "ALTER TABLE IF EXISTS contract_artifacts ADD COLUMN IF NOT EXISTS pdf_sha256 TEXT; "
    "ALTER TABLE IF EXISTS contract_artifacts ADD COLUMN IF NOT EXISTS docx_sha256_slotted TEXT; "
    "ALTER TABLE IF EXISTS contract_artifacts ADD COLUMN IF NOT EXISTS pdf_sha256_slotted TEXT; "
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


# Domain RAG corpus registry (change add-domain-rag-corpus-service). The DDL
# lives in src.bench.workspace_store.WORKSPACE_SCHEMA (domain-neutral kernel);
# the one thing that cannot live there is the retro-registration of the
# pre-registry default corpus, because it names a concrete domain key and the
# default index name — both belong to the application layer, not the kernel.
# Seed semantics: if a domain keyed 'legal' exists and has no rag_corpora row
# yet, insert one pointing at the configured default search index so the
# zero-migration compat path holds (legal keeps retrieving/ingesting the
# pre-existing global index). The index name is bound at execute time (not in
# the constant) so a test monkeypatching src.settings.SEARCH_INDEX_NAME is
# honored. Fully idempotent: the WHERE guard plus ON CONFLICT DO NOTHING make
# concurrent/repeated ensures no-ops.
_RAG_CORPORA_LEGAL_SEED = """
INSERT INTO rag_corpora (domain_id, index_name, sources, embedding_model, registered_by)
SELECT d.id, %s, '[]'::jsonb, NULL, 'system:retro-register'
FROM domains d
WHERE d.key = 'legal'
  AND NOT EXISTS (SELECT 1 FROM rag_corpora rc WHERE rc.domain_id = d.id)
ON CONFLICT DO NOTHING
"""


# The DDL is fully idempotent, so ensure_schema is memoized per database (keyed
# by dbname): the first call on a given DB creates/migrates; subsequent calls
# (every store/list/compare) are a cheap no-op. This matters because the store
# functions call ensure_schema defensively on every invocation.
_ensured_dbs: set[str] = set()
_ensure_lock = threading.Lock()

_LOG = logging.getLogger(__name__)

#: Tables whose presence defines "this database's schema is really there".
#:
#: Readiness is asserted by MEASURING these, never by "no exception was raised"
#: (fix-ensure-schema-lock-masking). Keep the list in step with the write paths:
#: a table missing here only makes the probe weaker, never wrong, but a table
#: listed here that no path creates would make every call fail the probe.
#:
#: Only tables that THIS function creates belong here. ``rubrics`` / ``criteria``
#: / ``prompts`` are deliberately absent: they come from ``harbor_seed.create_schema``
#: (the seeded fixture's own path), so listing them would make every probe on a
#: fresh DB fail for a reason that is not this function's business.
_REQUIRED_TABLES: tuple[str, ...] = (
    # eval engine
    "eval_runs",
    "eval_criteria_results",
    "compare_runs",
    "law_info",
    "clauses",
    "tag_dims",
    "pipeline_runs",
    # artifacts / keys / review
    "contract_artifacts",
    "api_keys",
    "api_eval_runs",
    "generation_jobs",
    "review_tasks",
    # bench kernel
    "knowledge_units",
    "domains",
    "ontology_templates",
    "authoring_tasks",
    "domain_agent_runs",
    "distribution_consumers",
    "corpus_chunks",
)

#: Lock wait used for the DDL. Overridable so the concurrency tests do not each
#: sit out the production 3s (a test proves the SEMANTICS, not the duration).
_LOCK_TIMEOUT_ENV = "SCHEMA_LOCK_TIMEOUT_MS"
_DEFAULT_LOCK_TIMEOUT_MS = 3000


def _lock_timeout_ms() -> int:
    raw = os.environ.get(_LOCK_TIMEOUT_ENV)
    try:
        value = int(raw) if raw else _DEFAULT_LOCK_TIMEOUT_MS
    except (TypeError, ValueError):
        value = _DEFAULT_LOCK_TIMEOUT_MS
    return max(1, value)


def _missing_required_tables(conn) -> list[str]:
    """Which required tables are absent — one round trip, no writes."""
    rows = conn.execute(
        "SELECT t FROM unnest(%s::text[]) AS t "
        "WHERE to_regclass('public.' || t) IS NULL",
        (list(_REQUIRED_TABLES),),
    ).fetchall()
    return [r["t"] for r in rows]


def _mark_ready(conn, key: str) -> None:
    """Mark ``key`` ready — but only after measuring that the tables are there."""
    missing = _missing_required_tables(conn)
    if missing:
        _LOG.error(
            "schema bootstrap for %s finished its DDL but %d required table(s) "
            "are still absent (%s); NOT marking ready",
            key, len(missing), ", ".join(missing),
        )
        return
    _ensured_dbs.add(key)


def _probe_and_mark(conn, key: str) -> None:
    """After a lock timeout: mark ready only if the tables measurably exist."""
    missing = _missing_required_tables(conn)
    if missing:
        _LOG.warning(
            "schema bootstrap for %s is incomplete (%d missing: %s); "
            "not marking ready — the next call will retry",
            key, len(missing), ", ".join(missing),
        )
        return
    _ensured_dbs.add(key)


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
            # A short lock timeout keeps concurrent first-boots from deadlocking
            # each other. Timing out is NOT success, though: see the handler
            # below and fix-ensure-schema-lock-masking.
            conn.execute(f"SET lock_timeout = '{_lock_timeout_ms()}ms'")
            # Repair missing primary keys BEFORE any CREATE ... REFERENCES runs.
            # Several tables declare ``REFERENCES eval_runs(id)``; on a database
            # whose ``eval_runs`` predates the IDENTITY-PK DDL, those FKs cannot
            # be created and the boot dies. Measured on the live pod 2026-11-18:
            # 16 rows, ids non-null and distinct, pg_constraint empty.
            conn.execute(_PK_REPAIRS)
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
            # knowledge-bench kernel tables (domain-neutral; see src/bench)
            from ..bench.store import BENCH_SCHEMA
            from ..bench.workspace_store import WORKSPACE_SCHEMA
            from ..bench.libraries import LIBRARY_SCHEMA

            conn.execute(BENCH_SCHEMA)
            conn.execute(WORKSPACE_SCHEMA)
            # Domain tree + shared corpus libraries (add-domain-tree-and-shared-
            # libraries). Runs after WORKSPACE_SCHEMA because its ALTERs touch
            # domains / knowledge_units, and it backfills the pre-tree rows.
            conn.execute(LIBRARY_SCHEMA)
            # Retro-register the legal domain's default corpus (see the seed's
            # comment). Import at call time so a monkeypatched
            # src.settings.SEARCH_INDEX_NAME is read, not the import-time
            # binding of this module.
            from src.settings import SEARCH_INDEX_NAME

            conn.execute(_RAG_CORPORA_LEGAL_SEED, (SEARCH_INDEX_NAME,))
            conn.execute(_ADDITIVE_COLUMNS)
            _mark_ready(conn, key)
            conn.commit()
        except psycopg.errors.LockNotAvailable:
            # Another process holds a lock we need. That is a normal race, not a
            # failure — but it is ALSO not evidence that the schema exists. The
            # old code assumed "the other process is building it" and marked the
            # DB ready anyway; when both sides timed out, nothing was built and
            # every later write failed with UndefinedTable from far away.
            #
            # So: do not raise (a race must not become an availability event),
            # do not cache (the next call retries), and let the measurement
            # decide whether we happen to be looking at a finished schema.
            _LOG.warning(
                "schema bootstrap for %s hit lock_timeout after %sms; "
                "will retry on the next call",
                key, _lock_timeout_ms(),
            )
            try:
                # The timed-out DDL left this session's transaction aborted, so
                # the probe cannot run until we end it. Rolling back is safe: the
                # DDL is idempotent and nothing was committed by this attempt.
                conn.rollback()
                _probe_and_mark(conn, key)
            except Exception:  # noqa: BLE001 - the probe is best-effort here
                # A probe failure must not turn a retryable race into a crash;
                # the cache stays empty either way, which is the safe outcome.
                pass
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
    channel: str = "text",
    unit_kind: str = "clause",
    subject_kind: Optional[str] = None,
    subject_key: Optional[str] = None,
    subject_version: Optional[str] = None,
    ruler_kind: Optional[str] = None,
    ruler_key: Optional[str] = None,
    ruler_digest: Optional[str] = None,
    gate: Optional[str] = None,
    outcome: Optional[str] = None,
    baseline_run_id: Optional[int] = None,
    provisional: bool = False,
) -> int:
    """Insert an evaluation run + its per-criterion verdicts. Returns the run id.

    The rubric/contract/task_desc are snapshotted as text so a run survives later
    edits or deletion of the rubric it used. Compare-driven columns
    (``compare_run_id``, ``prompt_name``, ``prompt_type``, ``variant_label``,
    ``draft_text``) are optional keyword-only args; standalone runs leave them
    null, compare runs populate them so the run is grouped under and traceable
    to its prompt without a foreign key.

    ``channel`` / ``unit_kind`` (keyword-only) label which evaluation channel
    produced the run and what kind of unit it evaluated. Defaults (``'text'`` /
    ``'clause'``) match the column defaults, so every legacy insert path reads
    exactly as before; the deterministic data-check channel passes
    ``channel='data'`` with its own unit kind (see src/bench/data_checks.py).

    The verdict-ledger args (``subject_*`` / ``ruler_*`` / ``gate`` / ``outcome``
    / ``baseline_run_id`` / ``provisional``) are all optional and default to
    None, so a caller that passes none of them writes the same row it always
    did. When ``outcome`` is omitted it is derived from ``all_pass`` (1 → pass,
    0 → fail) — never invented as 'inconclusive', which is a NEW semantic that
    must not be back-filled onto historical rows. Validation of the gate and
    outcome vocabularies lives in src/bench/verdicts.py and is applied by the
    callers that actually speak the ledger vocabulary; this low-level writer
    stays vocabulary-agnostic so every legacy path keeps working.
    """
    ensure_schema(db_path)
    now = datetime.now(timezone.utc).isoformat()
    effective_outcome = outcome if outcome is not None else (
        "pass" if result["all_pass"] else "fail"
    )

    def _do_insert():
        conn = connect(db_path)
        try:
            cur = conn.execute(
                "INSERT INTO eval_runs "
                "(rubric_name, contract_path, task_desc, score, max_score, all_pass, "
                " n_criteria, n_passed, summary, judge_model, scored_at, created_at, "
                " compare_run_id, prompt_name, prompt_type, variant_label, draft_text, "
                " channel, unit_kind, "
                " subject_kind, subject_key, subject_version, "
                " ruler_kind, ruler_key, ruler_digest, "
                " gate, outcome, baseline_run_id, provisional) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
                " %s,%s,%s, %s,%s,%s, %s,%s,%s,%s) "
                "RETURNING id",
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
                    channel,
                    unit_kind,
                    subject_kind,
                    subject_key,
                    subject_version,
                    ruler_kind,
                    ruler_key,
                    ruler_digest,
                    gate,
                    effective_outcome,
                    baseline_run_id,
                    bool(provisional),
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
                "       n_passed, n_criteria, judge_model, scored_at, "
                "       channel, unit_kind, "
                "       subject_kind, subject_key, subject_version, "
                "       ruler_kind, ruler_key, ruler_digest, "
                "       gate, outcome, baseline_run_id, provisional "
                "FROM eval_runs ORDER BY id DESC LIMIT %s",
                (limit,),
            ).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]
    return _retry_db_operation(_do_list)


def list_verdicts(
    subject_kind: Optional[str] = None,
    subject_key: Optional[str] = None,
    limit: int = 100,
    db_path=DEFAULT_DB,
    domain_paths: Optional[list[str]] = None,
) -> list[dict]:
    """Verdict-ledger rows, optionally narrowed to one subject.

    Returns the ledger columns only (subject / ruler / gate / outcome / baseline)
    plus the identity fields a trend line needs. Deliberately does NOT join
    ``eval_criteria_results``: a trend query over N runs should not drag N×M
    per-criterion rows along. Use :func:`get_run` for one run's detail.

    As in :func:`list_runs`, an omitted filter means "no narrowing", never
    "match the empty string".

    ``domain_paths`` narrows to runs attributed to those domain paths (the
    machine read face uses it to answer "what was judged in MY domain"). The
    attribution column is ``rubric_domain_id`` — the same one
    ``domain_rubrics.runs_for_domain`` reads, so a domain's verdict list and its
    run list cannot disagree about which runs are its own.
    """
    where, args = [], []
    if subject_kind is not None:
        where.append("subject_kind = %s")
        args.append(subject_kind)
    if subject_key is not None:
        where.append("subject_key = %s")
        args.append(subject_key)
    if domain_paths is not None:
        if not domain_paths:
            # An explicitly empty scope answers nothing. Returning everything
            # would turn a mis-scoped caller into a cross-domain reader.
            return []
        where.append(
            "rubric_domain_id IN (SELECT id FROM domains WHERE path = ANY(%s))"
        )
        args.append(list(domain_paths))
    clause = f"WHERE {' AND '.join(where)} " if where else ""

    def _do_list():
        conn = connect(db_path)
        try:
            rows = conn.execute(
                "SELECT id, rubric_name, score, all_pass, judge_model, scored_at, "
                "       channel, unit_kind, "
                "       subject_kind, subject_key, subject_version, "
                "       ruler_kind, ruler_key, ruler_digest, "
                "       gate, outcome, baseline_run_id, provisional "
                f"FROM eval_runs {clause}ORDER BY id DESC LIMIT %s",
                (*args, limit),
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
                "       scored_at, compare_run_id, prompt_name, prompt_type, variant_label, "
                "       channel, unit_kind, "
                "       subject_kind, subject_key, subject_version, "
                "       ruler_kind, ruler_key, ruler_digest, "
                "       gate, outcome, baseline_run_id, provisional "
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


def reap_stale_generation_jobs(db_path=DEFAULT_DB) -> int:
    """把上一个进程遗留的非终态生成任务扫成 `failed`；返回扫掉的行数。

    **为什么必须有这个**（审计 03 §10）：``generation_jobs`` 的终态只有后台任务
    自己在同一个进程里写（``background_tasks.add_task`` → try/except →
    completed/failed）。滚动部署、OOM、pod 被驱逐、或 SIGTERM 落在「202 已返回」
    与「任务收尾」之间时，这行就永远停在 ``pending`` 或 ``running``——而此前
    ``src/`` 里没有任何启动清扫、reaper 或 ``updated_at`` 超时。后果是客户端轮询
    ``GET /api/generation-jobs/{id}`` 被告知「还在跑」，UI 面板显示同样的谎。
    生成一次是几分钟的 LLM 调用，工作时间发版必然撞上。

    在进程启动时调用一次即可：此刻**本进程还没有任何在跑的任务**，所以凡是非终态
    行一定是上一个进程遗留的，可以无条件收掉。

    返回扫掉的行数（0 表示干净，便于启动日志打一行）。
    """
    ensure_schema(db_path)

    def _do_reap():
        conn = connect(db_path)
        try:
            cur = conn.execute(
                "UPDATE generation_jobs "
                "SET status='failed', error_message=%s, updated_at=%s "
                "WHERE status IN ('pending','running')",
                (
                    "interrupted by process restart",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            n = cur.rowcount or 0
            conn.commit()
            return n
        finally:
            conn.close()

    return _retry_db_operation(_do_reap)


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
