# agent-metrics Specification

## Purpose
Capture per-run agent execution metrics — node timings, model calls, reviewer suggestions, human checkpoint participation, and evaluation linkage — so contract-drafting runs can be profiled, audited, and compared without instrumenting each node ad hoc.

## Requirements
### Requirement: agent_runs table schema
The system SHALL create a new PostgreSQL table `agent_runs` with the following columns: `id` (BIGSERIAL PK), `thread_id` (TEXT, LangGraph thread), `contract_type` (TEXT), `tags` (JSONB), `node_timings` (JSONB, per-node duration in seconds), `model_calls` (JSONB, array of {model, tokens, cost, latency}), `review_suggestions` (JSONB, all suggestions from reviewers), `suggestions_applied` (JSONB, which were applied in v2), `total_slots` (INT), `human_filled_slots` (INT), `eval_run_id` (BIGINT FK to eval_runs), `deepeval_scores` (JSONB), `total_duration` (FLOAT, seconds), `created_at` (TIMESTAMPTZ).

#### Scenario: Table creation
- **WHEN** the database migration runs
- **THEN** the `agent_runs` table SHALL be created with all specified columns
- **THEN** the table SHALL have a foreign key constraint on `eval_run_id` referencing `eval_runs(id)`

### Requirement: Per-node timing tracking
Each node in the LangGraph SHALL measure its execution duration using `time.perf_counter()`. The timing SHALL be stored in the `node_timings` JSONB column as a dict mapping node name to duration in seconds.

#### Scenario: Node timings recorded
- **WHEN** the graph completes with nodes generate_v1 (2.3s), review_panel (8.1s), synthesize (1.2s)
- **THEN** the `node_timings` column SHALL contain `{"generate_v1": 2.3, "review_panel": 8.1, "synthesize": 1.2, ...}`

### Requirement: Model call tracking
Each LLM call SHALL record the model name, token consumption (input + output), estimated cost, and latency. These records SHALL be aggregated into the `model_calls` JSONB array.

#### Scenario: Model calls tracked
- **WHEN** the review panel calls 3 models (kimi-k3, qwen-3.7-plus, glm-5.2)
- **THEN** the `model_calls` array SHALL contain 3 entries, each with `model`, `input_tokens`, `output_tokens`, `total_tokens`, `cost_usd`, `latency_seconds`

### Requirement: MCP tools for agent metrics
The system SHALL expose three new MCP tools in `fd-coding-law-bench-mcp`:
- `agent_run_store(run_data: dict) -> int`: Insert a new agent run record, return the run ID
- `agent_run_get(run_id: int) -> dict`: Retrieve a full agent run by ID
- `agent_run_list(limit: int = 20) -> list[dict]`: List recent agent runs with summary stats

#### Scenario: Store and retrieve agent run
- **WHEN** `agent_run_store` is called with full run data
- **THEN** a new row SHALL be inserted into `agent_runs`
- **THEN** the returned ID SHALL be usable with `agent_run_get` to retrieve the full record

#### Scenario: List agent runs
- **WHEN** `agent_run_list(limit=5)` is called
- **THEN** the 5 most recent agent runs SHALL be returned with summary fields (id, contract_type, total_duration, created_at)

### Requirement: HTTP endpoints for agent metrics
The law-bench FastAPI SHALL expose new HTTP endpoints under `/agent-runs`:
- `POST /agent-runs` — store a new agent run
- `GET /agent-runs/{run_id}` — get a specific run
- `GET /agent-runs` — list recent runs

#### Scenario: HTTP API for agent metrics
- **WHEN** a client calls `GET /agent-runs?limit=10`
- **THEN** the API SHALL return the 10 most recent agent runs as JSON

### Requirement: Review quality tracking
The system SHALL track which reviewer suggestions were accepted by the user (at CP1) and which were applied in the v2 draft. The `review_suggestions` column SHALL store all original suggestions; `suggestions_applied` SHALL store the subset that were applied.

#### Scenario: Review quality metrics
- **WHEN** the user accepts 3 of 5 suggestions at CP1
- **THEN** `suggestions_applied` SHALL contain those 3 suggestions
- **THEN** the system SHALL compute a `suggestion_acceptance_rate` = 3/5 = 0.6

### Requirement: Slot coverage tracking
The system SHALL track the total number of slots in the contract and how many were filled by the human (via quiz) vs by the LLM (via fill node). The `total_slots`, `human_filled_slots` columns SHALL record these counts.

#### Scenario: Slot coverage stats
- **WHEN** the contract has 10 slots and the human fills all 10 via the quiz
- **THEN** `total_slots` = 10, `human_filled_slots` = 10
- **THEN** `slot_coverage_rate` = 1.0
