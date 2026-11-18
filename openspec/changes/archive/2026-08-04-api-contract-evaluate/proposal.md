# API Contract Evaluate

## Why

The contract evaluation engine exists but is only accessible through MCP tools (`contract_evaluate`, `pipeline_run`). External clients have no REST API to evaluate contracts against rubrics.

## What Changes

- New `api_eval_runs` table for async evaluation storage
- `POST /api/evaluate` — submit contract for async evaluation, returns `run_id`
- `GET /api/evaluate/{run_id}` — poll for results
- Background task processing via FastAPI `BackgroundTasks`
- Accepts inline text or file upload, evaluates against a named rubric

## Capabilities

### New Capabilities
- `api-evaluate`: Async REST API for contract evaluation with polling

### Modified Capabilities

## Impact

- New route file: `src/web/routes/evaluate.py`
- New models in `src/web/models.py`
- New table in `src/eval/store.py`
- Reuses existing `evaluate_contract()` from `src/eval/scoring.py`
