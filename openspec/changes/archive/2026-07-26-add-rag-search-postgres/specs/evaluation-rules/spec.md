# evaluation-rules Specification (delta)

## MODIFIED Requirements

### Requirement: Rubric and Criterion Storage
The system SHALL store evaluation rubrics and their criteria in a PostgreSQL database addressed by the `database_url` environment variable. Each rubric SHALL have a name, context, source, source_path, and description. Each criterion SHALL belong to exactly one rubric and SHALL have a name, description, guidance, and ordinal. The combination of rubric and criterion name SHALL be unique.

#### Scenario: Store a harbor rubric with its criteria
- **WHEN** the extraction script runs against harbor's `default-rubric.toml`
- **THEN** a `task_quality` rubric row is stored with `source = harbor:v0.20.0`, `context = check`, and `source_path` pointing at the harbor TOML file
- **AND** each of its 11 criteria is stored with name, description, and guidance

#### Scenario: Query criteria of a rubric
- **WHEN** a caller queries criteria by rubric name
- **THEN** all criteria for that rubric are returned ordered by `ordinal`

### Requirement: Compare Runs Grouping Table
The system SHALL add a `compare_runs` table to the PostgreSQL database addressed by `database_url`, created idempotently by `src/eval/store.py::ensure_schema` (alongside `eval_runs` and `eval_criteria_results`). Columns: `id` primary key, `label`, `contract_type`, `rubric_name`, `task_desc`, `gen_mode`, `n_drafts`, `created_at`. One `compare_runs` row groups the `eval_runs` rows that belong to a single compare via the `eval_runs.compare_run_id` snapshot column.

#### Scenario: The compare_runs table is created idempotently
- **WHEN** `ensure_schema` runs on a fresh database
- **THEN** the `compare_runs` table exists with all columns
- **AND** re-running `ensure_schema` leaves it unchanged

### Requirement: Idempotent Additive-Column Migration
The system SHALL migrate existing databases to the new schema via a guarded `ALTER TABLE … ADD COLUMN IF NOT EXISTS` helper invoked from `ensure_schema`, checking `information_schema.columns` before each add. The migration SHALL run on every startup, SHALL be idempotent (a no-op once columns exist), and SHALL NOT touch any existing row's data (new columns default to null).

#### Scenario: An existing DB is migrated on startup
- **WHEN** `ensure_schema` runs against a DB that predates this change
- **THEN** `prompt_type` is added to `prompts`, `compare_runs` is created, and the five new columns are added to `eval_runs`
- **AND** existing `eval_runs` and `prompts` rows have null/blank new columns

#### Scenario: Migration is idempotent
- **WHEN** `ensure_schema` runs a second time
- **THEN** no `ALTER TABLE` is attempted for columns that already exist
- **AND** no error is raised

## ADDED Requirements

### Requirement: Postgres Connection and Schema Management
The system SHALL obtain a PostgreSQL connection from the `database_url` environment variable (a libpq DSN, e.g. `postgresql://user:pass@host:5432/db`). The web layer SHALL resolve the active connection via the `get_db()` dependency seam, which SHALL no longer return a filesystem `Path`. Schema creation for `rubrics`, `criteria`, `prompts`, `eval_runs`, `eval_criteria_results`, and `compare_runs` SHALL be idempotent (`CREATE TABLE IF NOT EXISTS`), SHALL enforce foreign keys with `ON DELETE CASCADE` where the prior SQLite schema did, and SHALL use `BIGINT GENERATED ALWAYS AS IDENTITY` for auto-increment primary keys. Insert paths SHALL obtain generated primary keys via `RETURNING id`.

#### Scenario: get_db returns a connection from database_url
- **WHEN** a request handler depends on `get_db()`
- **THEN** it receives a live PostgreSQL connection resolved from `database_url`
- **AND** no filesystem path is involved in resolving the database

#### Scenario: Schema is created idempotently with FK cascade
- **WHEN** `ensure_schema` runs on a fresh PostgreSQL database
- **THEN** all six tables are created with identity primary keys
- **AND** deleting a rubric cascades to its criteria via the `ON DELETE CASCADE` foreign key

#### Scenario: Generated ids are obtained via RETURNING
- **WHEN** a rubric or prompt is inserted
- **THEN** the new row's generated `id` is returned from the same statement via `RETURNING id`
- **AND** no separate `lastrowid` lookup is used
