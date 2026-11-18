## ADDED Requirements

### Requirement: Submit contract evaluation via REST API
The system SHALL provide a REST API endpoint `POST /api/evaluate` that accepts a contract and rubric name, creates an evaluation job, and returns a run ID for polling.

#### Scenario: Submit evaluation with inline contract text
- **WHEN** client sends `POST /api/evaluate` with `rubric` (form field) and `contract_text` (form field)
- **THEN** system creates an `api_eval_runs` row with status `pending`
- **AND** returns HTTP 202 Accepted with `{ "run_id": <int>, "status": "pending" }`
- **AND** starts evaluation in background task

#### Scenario: Submit evaluation with file upload
- **WHEN** client sends `POST /api/evaluate` with `rubric` (form field) and `contract_file` (file upload)
- **THEN** system reads file content as UTF-8 text
- **AND** creates an `api_eval_runs` row with status `pending`
- **AND** returns HTTP 202 Accepted with `{ "run_id": <int>, "status": "pending" }`
- **AND** starts evaluation in background task

#### Scenario: Submit evaluation with missing rubric
- **WHEN** client sends `POST /api/evaluate` without `rubric` field
- **THEN** system returns HTTP 400 Bad Request with error message

#### Scenario: Submit evaluation with missing contract
- **WHEN** client sends `POST /api/evaluate` without `contract_text` or `contract_file`
- **THEN** system returns HTTP 400 Bad Request with error message

#### Scenario: Submit evaluation with non-existent rubric
- **WHEN** client sends `POST /api/evaluate` with `rubric` that does not exist
- **THEN** system returns HTTP 404 Not Found with error message

### Requirement: Retrieve evaluation result via polling
The system SHALL provide a REST API endpoint `GET /api/evaluate/{run_id}` that returns the current status and result of an evaluation job.

#### Scenario: Retrieve pending evaluation
- **WHEN** client sends `GET /api/evaluate/{run_id}` for a job with status `pending`
- **THEN** system returns HTTP 200 OK with `{ "run_id": <int>, "status": "pending", "rubric_name": <str>, "created_at": <timestamp> }`

#### Scenario: Retrieve running evaluation
- **WHEN** client sends `GET /api/evaluate/{run_id}` for a job with status `running`
- **THEN** system returns HTTP 200 OK with `{ "run_id": <int>, "status": "running", "rubric_name": <str>, "created_at": <timestamp> }`

#### Scenario: Retrieve completed evaluation
- **WHEN** client sends `GET /api/evaluate/{run_id}` for a job with status `completed`
- **THEN** system returns HTTP 200 OK with full result including:
  - `run_id`, `status`, `rubric_name`
  - `score`, `all_pass`, `n_passed`, `n_criteria`
  - `criteria_results` (array of per-criterion verdicts)
  - `judge_model`
  - `created_at`, `completed_at`

#### Scenario: Retrieve failed evaluation
- **WHEN** client sends `GET /api/evaluate/{run_id}` for a job with status `failed`
- **THEN** system returns HTTP 200 OK with `{ "run_id": <int>, "status": "failed", "error_message": <str>, "rubric_name": <str>, "created_at": <timestamp> }`

#### Scenario: Retrieve non-existent evaluation
- **WHEN** client sends `GET /api/evaluate/{run_id}` for a run_id that does not exist
- **THEN** system returns HTTP 404 Not Found with error message

### Requirement: Store evaluation results in dedicated table
The system SHALL store API evaluation results in a new table `api_eval_runs` with fields for status tracking, contract text, rubric name, evaluation results, and timestamps.

#### Scenario: Create api_eval_runs row on submission
- **WHEN** client submits evaluation via `POST /api/evaluate`
- **THEN** system inserts a row into `api_eval_runs` with:
  - `rubric_name` from request
  - `contract_text` from request (file content or inline text)
  - `status` = `pending`
  - `created_at` = current timestamp
  - All result fields (`score`, `all_pass`, etc.) = NULL

#### Scenario: Update status to running when evaluation starts
- **WHEN** background task begins evaluation
- **THEN** system updates `api_eval_runs` row with `status` = `running`

#### Scenario: Update status to completed when evaluation succeeds
- **WHEN** background task completes evaluation successfully
- **THEN** system updates `api_eval_runs` row with:
  - `status` = `completed`
  - `score`, `all_pass`, `n_passed`, `n_criteria` from evaluation result
  - `results` = JSONB with full `criteria_results` array
  - `judge_model` from evaluation result
  - `completed_at` = current timestamp

#### Scenario: Update status to failed when evaluation fails
- **WHEN** background task fails during evaluation (LLM error, exception, etc.)
- **THEN** system updates `api_eval_runs` row with:
  - `status` = `failed`
  - `error_message` = error description
  - `completed_at` = current timestamp

### Requirement: List recent API evaluations
The system SHALL provide a REST API endpoint `GET /api/evaluate` that lists recent API evaluation runs.

#### Scenario: List recent evaluations
- **WHEN** client sends `GET /api/evaluate`
- **THEN** system returns HTTP 200 OK with array of recent evaluations (most recent first)
- **AND** each evaluation includes: `run_id`, `status`, `rubric_name`, `score`, `all_pass`, `created_at`, `completed_at`
- **AND** default limit is 20 evaluations

#### Scenario: List evaluations with custom limit
- **WHEN** client sends `GET /api/evaluate?limit=50`
- **THEN** system returns up to 50 recent evaluations

### Requirement: Reuse existing evaluation engine
The system SHALL reuse the existing `evaluate_contract()` function from `src/eval/scoring.py` to perform the actual evaluation logic.

#### Scenario: Evaluate contract using existing engine
- **WHEN** background task processes an evaluation job
- **THEN** system calls `evaluate_contract(contract_text, rubric_name, db_path)` from `src/eval/scoring.py`
- **AND** stores the returned result in `api_eval_runs.results` as JSONB
- **AND** extracts `score`, `all_pass`, `n_passed`, `n_criteria`, `judge_model` into dedicated columns

### Requirement: Run evaluation in background task
The system SHALL run the evaluation in a FastAPI `BackgroundTasks` handler to avoid blocking the HTTP response.

#### Scenario: Return immediately with run_id
- **WHEN** client submits evaluation via `POST /api/evaluate`
- **THEN** system returns HTTP 202 Accepted immediately
- **AND** evaluation runs in background task after response is sent

#### Scenario: Background task handles errors gracefully
- **WHEN** background task encounters an error during evaluation
- **THEN** system catches the exception
- **AND** updates `api_eval_runs.status` to `failed`
- **AND** stores error message in `api_eval_runs.error_message`
- **AND** does not crash the server or affect other requests
