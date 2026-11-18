## ADDED Requirements

### Requirement: Compare Runs Grouping Table
The system SHALL add a `compare_runs` table to `db/evaluation_rules.db`, created idempotently by `src/eval/store.py::ensure_schema` (alongside `eval_runs` and `eval_criteria_results`). Columns: `id` PK, `label`, `contract_type`, `rubric_name`, `task_desc`, `gen_mode`, `n_drafts`, `created_at`. One `compare_runs` row groups the `eval_runs` rows that belong to a single compare via the `eval_runs.compare_run_id` snapshot column.

#### Scenario: The compare_runs table is created idempotently
- **WHEN** `ensure_schema` runs on a fresh DB
- **THEN** the `compare_runs` table exists with all columns
- **AND** re-running `ensure_schema` leaves it unchanged

### Requirement: Compare-Driven Columns on eval_runs
The system SHALL add nullable, snapshotted columns to `eval_runs`: `compare_run_id` (INTEGER, soft reference to `compare_runs.id`, no FK constraint), `prompt_name` (TEXT), `prompt_type` (TEXT), `variant_label` (TEXT), and `draft_text` (TEXT). Existing standalone (non-compare) runs SHALL continue to work with these columns null. No FK constraint SHALL be introduced, so a run survives deletion of its prompt or compare (snapshot discipline).

#### Scenario: Standalone runs keep working
- **WHEN** `src/eval/run.py` stores a standalone eval run after migration
- **THEN** the run is stored with `compare_run_id`, `prompt_name`, `prompt_type`, `variant_label`, and `draft_text` all null
- **AND** `--list-runs` output is unchanged

#### Scenario: A compare run records its prompt and draft
- **WHEN** a compare stores an `eval_runs` row
- **THEN** `compare_run_id`, `prompt_name`, `prompt_type`, `variant_label`, and `draft_text` are populated from the prompt and draft used
- **AND** renaming or deleting the prompt afterward does not change the stored row

### Requirement: Idempotent Additive-Column Migration
The system SHALL migrate existing databases to the new schema via a guarded `ALTER TABLE … ADD COLUMN` helper invoked from `ensure_schema`, checking `PRAGMA table_info` before each add. The migration SHALL run on every startup, SHALL be idempotent (a no-op once columns exist), and SHALL NOT touch any existing row's data (new columns default to null).

#### Scenario: An existing DB is migrated on startup
- **WHEN** `ensure_schema` runs against a DB that predates this change
- **THEN** `prompt_type` is added to `prompts`, `compare_runs` is created, and the five new columns are added to `eval_runs`
- **AND** existing `eval_runs` and `prompts` rows have null/blank new columns

#### Scenario: Migration is idempotent
- **WHEN** `ensure_schema` runs a second time
- **THEN** no `ALTER TABLE` is attempted for columns that already exist
- **AND** no error is raised
