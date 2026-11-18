## Context

The contract evaluation engine (`src/eval/scoring.py`) evaluates contract text against a rubric's criteria using LLM judging (deepeval GEval, strict_mode). It's currently reachable only through:
- MCP tool `contract_evaluate` — synchronous, full rubric only
- `pipeline_run` — auto-selects rubric, part of generate→fill→evaluate loop
- `compare_run` — compares prompts, not standalone eval

External clients (web UIs, CI pipelines, third-party integrations) need a REST API to submit a contract for evaluation and retrieve results asynchronously.

**Constraints:**
- FastAPI app at `src/web/app.py` with APIRouter pattern in `src/web/routes/api.py`
- DB is PostgreSQL via psycopg2, connection through `src/eval/db.py`
- Existing `ensure_schema()` in `src/eval/store.py` handles table creation idempotently
- `evaluate_contract()` is sync, uses ThreadPoolExecutor internally — must run in background thread

## Goals / Non-Goals

**Goals:**
- REST API to submit contract evaluation jobs asynchronously
- Accept contract text inline or via file upload
- Evaluate against a named rubric (all criteria)
- Store results in a dedicated `api_eval_runs` table
- Poll-based result retrieval

**Non-Goals:**
- Criterion-level filtering (pick individual criteria) — add later if needed
- Multi-rubric composition — one rubric per evaluation
- Real-time streaming (SSE/WebSocket) — polling is sufficient
- Auto-cleanup of old runs — add when table grows
- Concurrency limits — add if LLM rate-limits bite

## Decisions

### 1. Async via FastAPI BackgroundTasks (not Celery/worker)

**Choice:** Use FastAPI's built-in `BackgroundTasks` for async evaluation.

**Rationale:**
- Zero infrastructure — no Redis, no worker process
- Fits the use case: low-volume, LLM-bound (not CPU-bound)
- If server restarts mid-eval, the run stays `pending`/`running` — client can retry or we add a reaper later
- Celery/ARQ adds operational complexity for marginal benefit at this scale

**Alternatives considered:**
- Celery + Redis: robust but overkill, adds dependency
- DB polling worker: survives restarts but adds complexity
- Sync endpoint: blocks for 30-60s, bad UX

### 2. Separate table `api_eval_runs` (not reuse `eval_runs`)

**Choice:** New table `api_eval_runs` with its own schema.

**Rationale:**
- `eval_runs` is tied to MCP/pipeline/compare workflows with different lifecycle
- API runs have async state machine (pending → running → completed/failed)
- Cleaner separation: API consumers don't see MCP internals
- Can evolve independently (add API-specific metadata, TTL, etc.)

**Alternatives considered:**
- Reuse `eval_runs` with extra columns: muddies semantics, harder to query
- Single table with `source` column: works but conflates concerns

### 3. Store contract_text in DB (not file path)

**Choice:** Store the full contract text in `api_eval_runs.contract_text`.

**Rationale:**
- Self-contained records — no dangling file references
- Text is typically <100KB, fits comfortably in TEXT column
- Simplifies retrieval and debugging
- If files are huge, we can add MinIO storage later

**Alternatives considered:**
- Store file path: breaks if file is deleted, requires cleanup
- MinIO storage: overkill for text, adds dependency

### 4. Multipart form-data for file upload (not JSON + base64)

**Choice:** `POST /api/evaluate` accepts `multipart/form-data` with `contract_file` (UploadFile) OR `contract_text` (form field).

**Rationale:**
- Standard pattern for file uploads in FastAPI
- Client doesn't need to base64-encode large files
- Can accept both file and text in one endpoint (one required)

**Alternatives considered:**
- JSON with base64: inefficient, client must encode
- Separate endpoints for file vs text: duplicates logic

### 5. Reuse `evaluate_contract()` directly (not refactor)

**Choice:** Call `evaluate_contract()` from `src/eval/scoring.py` as-is, wrap in background task.

**Rationale:**
- Already does what we need: loads rubric, evaluates criteria concurrently, returns structured result
- No reason to duplicate or refactor
- Just need to adapt the result to our DB schema

**Alternatives considered:**
- Refactor `evaluate_contract()` to be more modular: YAGNI, it works
- Write new eval logic: duplicates effort

### 6. Polling interval: client decides (no server guidance)

**Choice:** Return `run_id` immediately, client polls `GET /api/evaluate/{run_id}` every N seconds.

**Rationale:**
- Simple, stateless from server perspective
- Evaluation takes 10-60s depending on criteria count
- Client can choose polling frequency based on UX needs
- If we want to guide, add `Retry-After` header (optional, lazy)

**Alternatives considered:**
- Webhooks: adds complexity, requires callback URL management
- SSE: overkill for single-shot async operation
- Long-polling: ties up connection, no benefit over simple poll

## Risks / Trade-offs

**[Risk] BackgroundTasks tied to worker process lifecycle**
→ If server restarts mid-evaluation, run stays `pending`/`running` forever.
→ Mitigation: Add a reaper job later that marks old `running` tasks as `failed` after timeout. For now, document this limitation.

**[Risk] No concurrency limit on evaluations**
→ If many clients submit evaluations simultaneously, could hammer LLM API rate limits.
→ Mitigation: Monitor LLM errors. If rate-limits bite, add a semaphore (e.g., `asyncio.Semaphore(5)`) to limit concurrent evaluations. Lazy until proven necessary.

**[Risk] Large contract texts in DB**
→ Storing full contract text in `api_eval_runs` could bloat table if contracts are huge or numerous.
→ Mitigation: TEXT column handles up to 1GB. Typical contracts are <100KB. If table grows large, add TTL or archive old runs. Lazy until proven necessary.

**[Risk] LLM judge failures not handled gracefully**
→ `evaluate_contract()` can fail if LLM API is down or returns errors.
→ Mitigation: Wrap background task in try/except, update `api_eval_runs.status` to `failed` with `error_message`. Client sees failure via polling.

**[Trade-off] Synchronous DB inserts in background task**
→ Background task runs sync `evaluate_contract()` + sync DB inserts. Blocks the background thread.
→ Acceptable because: BackgroundTasks runs in threadpool anyway, not event loop. Low concurrency means no bottleneck. If throughput matters, refactor to async DB driver (big change, YAGNI).

## Migration Plan

**Deploy:**
1. Add `api_eval_runs` table to `ensure_schema()` in `src/eval/store.py`
2. Add new routes to `src/web/routes/api.py`
3. Add Pydantic models to `src/web/models.py`
4. No data migration needed (new table, no existing data)

**Rollback:**
1. Remove routes and models
2. Table remains in DB (no data loss, can drop manually if needed)

**Testing:**
1. Unit test: submit evaluation, poll for result, verify status transitions
2. Integration test: evaluate a real contract against a real rubric
3. Error test: submit with invalid rubric, verify 404
4. Error test: submit with no contract text/file, verify 400

## Open Questions

None. Design is complete and decisions are made.
