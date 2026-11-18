## 1. DB connection helper

- [x] 1.1 Add a process-wide cached connection helper in `src/eval/db.py` (e.g. `get_shared_conn()`) that lazily opens a single `psycopg.Connection` from `_dsn()` and reuses it across calls; add a `close_shared_conn()` for shutdown.
- [x] 1.2 Update `connect(db)` callers in the MCP wrapper path to route through the shared helper when no explicit `db` is injected, so per-call `psycopg.connect(...)` stops happening for tool invocations.
- [x] 1.3 Add a small unit test for the cached helper: first call opens, second call returns the same object, `close_shared_conn()` forces a reopen.

## 2. Async tool surface - read-only tools

- [x] 2.1 Convert `tools/law_info.py` (`law_types`, `law_info`, `law_references`) to `async def` + `await anyio.to_thread.run_sync(...)`.
- [x] 2.2 Convert `tools/tags.py` (`tag_vocab_list`, `tag_validate`) to `async def` + `run_sync`.
- [x] 2.3 Convert `tools/prompts.py` (`prompt_list`, `prompt_get`, `prompt_create`, `prompt_update`, `prompt_delete`) to `async def` + `run_sync`.
- [x] 2.4 Convert `tools/rubrics.py` (`rubric_get`, `rubric_create`, `rubric_update`, `rubric_delete`, `criterion_add`, `criterion_update`, `criterion_delete`, `criterion_reorder`) to `async def` + `run_sync`.
- [x] 2.5 Convert read paths in `tools/clauses.py` (`clause_list`, `clause_get`) to `async def` + `run_sync`.
- [x] 2.6 Convert `tools/rag.py` (`search_clauses`) to `async def` + `run_sync`.
- [x] 2.7 Convert read paths in `tools/evaluate.py` (`rubric_list`, `run_list`, `run_get`) to `async def` + `run_sync`.
- [x] 2.8 Convert read paths in `tools/compare.py` (`compare_list`, `compare_get`, `compare_matrix`, `run_draft`) to `async def` + `run_sync`.
- [x] 2.9 Convert read paths in `tools/pipeline.py` (`pipeline_list`, `pipeline_get`) to `async def` + `run_sync`. For `pipeline_get`, wrap the multi-call sequence (get_pipeline_run + get_run) in a single `run_sync` via a local helper.

## 3. Async tool surface - write / heavy tools

- [x] 3.1 Convert write paths in `tools/clauses.py` (`clause_update`, `clause_delete`, `clause_review`) to `async def` + `run_sync`.
- [x] 3.2 Convert `tools/evaluate.py` `contract_evaluate` to `async def` + single `run_sync` around the outermost `evaluate_contract` + `store_result` sequence.
- [x] 3.3 Convert `tools/generate.py` `contract_generate` to `async def` + `run_sync` (including the `load_vocab_from_db` + `tag_vocab_for_type` tail when `include_current_tags` is set).
- [x] 3.4 Convert `tools/compare.py` `compare_run` to `async def` + single `run_sync` around the full draft+judge loop.
- [x] 3.5 Convert `tools/pipeline.py` `pipeline_run` to `async def` + single `run_sync` around `run_pipeline(...)`.

## 4. Test harness

- [x] 4.1 Add `anyio` test support to `tests/conftest.py` (mark the suite with `anyio` or configure `pytest-anyio`), and replace any sync `mcp.call_tool(...)` helper with the async equivalent.
- [x] 4.2 Update `tests/test_law_info.py`, `tests/test_tags.py`, `tests/test_prompts.py`, `tests/test_rubrics.py` to `async def test_...` + `await mcp.call_tool(...)`.
- [x] 4.3 Update `tests/test_clauses.py`, `tests/test_rag_tool.py` to async.
- [x] 4.4 Update `tests/test_evaluate_tool.py`, `tests/test_compare.py`, `tests/test_pipeline.py`, `tests/test_generate_tool.py` to async.
- [x] 4.5 Update `tests/test_server.py` and `tests/test_tools_registration.py` to async where they invoke tools.

## 5. Verification

- [x] 5.1 Run the full `pytest` suite under the async harness; confirm all tests pass.
- [x] 5.2 Start the stdio server (`python -m fd_coding_law_bench_mcp`) and invoke at least one tool from a live MCP client (e.g. Claude Code) to confirm the wire contract is unchanged.
- [x] 5.3 Write a small concurrent smoke script that fires `pipeline_run`, `contract_evaluate`, and `clause_list` in parallel via `asyncio.gather`; confirm total wall-clock is closer to the slowest call than the sum.
