## 1. Database Schema & CRUD

- [x] 1.1 Add `api_eval_runs` table DDL to `ensure_schema()` in `src/eval/store.py`
- [x] 1.2 Add `store_api_eval_run()` function to insert a new row (returns run_id)
- [x] 1.3 Add `update_api_eval_run()` function to update status/results/error
- [x] 1.4 Add `get_api_eval_run()` function to fetch a single run by id
- [x] 1.5 Add `list_api_eval_runs()` function to fetch recent runs with limit

## 2. Pydantic Models

- [x] 2.1 Add `EvaluateSubmit` response model (run_id, status) to `src/web/models.py`
- [x] 2.2 Add `EvaluateRunDetail` response model (full result with criteria_results)
- [x] 2.3 Add `EvaluateRunSummary` response model (list item without criteria_results)

## 3. Route Handlers

- [x] 3.1 Add `POST /api/evaluate` route — accept multipart form (rubric + contract_text OR contract_file), validate inputs, insert row, start background task, return 202
- [x] 3.2 Add `GET /api/evaluate/{run_id}` route — fetch run, return full detail or 404
- [x] 3.3 Add `GET /api/evaluate` route — list recent runs with optional `limit` query param

## 4. Background Task

- [x] 4.1 Implement `_run_evaluation()` background function — update status to `running`, call `evaluate_contract()`, update status to `completed` with results, or `failed` with error_message on exception

## 5. Integration

- [x] 5.1 Wire routes into existing APIRouter in `src/web/routes/api.py`
- [x] 5.2 Verify `ensure_schema()` creates table on app startup
