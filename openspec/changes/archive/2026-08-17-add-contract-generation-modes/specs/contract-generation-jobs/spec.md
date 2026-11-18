# spec delta — contract-generation-jobs (NEW)

## ADDED Requirements

### Requirement: Uniform Async Generation-Job Record
The system SHALL persist a `generation_jobs` row for every async generation run (modes D/E/F/G) with columns `id`, `kind` (`'batch' | 'pipeline' | 'auto_reject' | 'regenerate'`), `contract_type`, `status` (`'pending' | 'running' | 'completed' | 'failed'`), `result_ref` (JSON text pointer to the mode's real output), `error_message`, `created_at`, `updated_at`. The table SHALL be created idempotently by `ensure_schema()` on app startup.

#### Scenario: Table created on startup
- **WHEN** the app starts and `ensure_schema()` runs
- **THEN** the `generation_jobs` table exists with the columns above

#### Scenario: Insert a pending job
- **WHEN** a caller invokes `store_generation_job(kind='pipeline', contract_type='sale')`
- **THEN** a row is inserted with `status='pending'` and its `id` is returned

#### Scenario: Update to completed with result_ref
- **WHEN** a background task finishes and calls `update_generation_job(id, status='completed', result_ref='{"pipeline_run_id":42}')`
- **THEN** the row's `status`, `result_ref`, and `updated_at` reflect the change

### Requirement: Submit Async Generation Job
The system SHALL expose `POST /api/contracts/{contract_type}/{mode-route}` (where mode-route is one of `pipeline`, `auto-reject`, `regenerate-template`) that validates the contract type, inserts a `generation_jobs` row with the matching `kind`, schedules the work via FastAPI `BackgroundTasks`, and returns `202` with `{job_id, status:'pending'}`. It SHALL return 404 for an unknown contract type.

#### Scenario: Submit a pipeline job
- **WHEN** a client `POST /api/contracts/sale/pipeline` with a valid body
- **THEN** the response is `202` with `{job_id, status:'pending'}` and a background task runs `run_self_heal_pipeline`

#### Scenario: Unknown type returns 404
- **WHEN** a client `POST /api/contracts/does_not_exist/pipeline`
- **THEN** the response status is 404

### Requirement: Poll Generation Job
The system SHALL expose `GET /api/generation-jobs/{job_id}` returning the full job row (`id, kind, contract_type, status, result_ref, error_message, created_at, updated_at`), and `GET /api/generation-jobs` returning the most recent jobs (default 20). A missing `job_id` SHALL return 404.

#### Scenario: Poll a running job
- **WHEN** a client `GET /api/generation-jobs/{id}` for a job still running
- **THEN** the response is `{status:'running', ...}` without `result_ref`

#### Scenario: Poll a completed job
- **WHEN** a client `GET /api/generation-jobs/{id}` for a completed job
- **THEN** the response includes `status:'completed'` and `result_ref` pointing at the mode's output

#### Scenario: Poll a failed job
- **WHEN** a client `GET /api/generation-jobs/{id}` for a failed job
- **THEN** the response includes `status:'failed'` and `error_message`

#### Scenario: Missing job returns 404
- **WHEN** a client `GET /api/generation-jobs/999999`
- **THEN** the response status is 404

### Requirement: Sync Batch Generation
The system SHALL expose `POST /api/contracts/{contract_type}/generate-batch` (mode D) that generates the contract across the requested (or enumerated) tag combinations in parallel with throttling and returns a sync JSON body `{results, success_count, failure_count}` plus per-item file URLs. It SHALL return 404 for an unknown contract type.

#### Scenario: Batch generate explicit combos
- **WHEN** a client `POST /api/contracts/sale/generate-batch` with `tag_combinations=[{"stance":"balanced"}]`
- **THEN** the response is `200` with `success_count >= 1` and each result carrying a `docx_url`/`pdf_url`

#### Scenario: Unknown type returns 404
- **WHEN** a client `POST /api/contracts/does_not_exist/generate-batch`
- **THEN** the response status is 404
