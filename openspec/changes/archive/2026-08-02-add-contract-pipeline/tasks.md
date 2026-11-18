## 1. Dependencies + scaffold

- [x] 1.1 Add `langgraph>=0.2` and `langchain-core>=0.3` to `fd-coding-law-bench-mcp/pyproject.toml` `[project.dependencies]`; install into the shared law-bench venv (`uv pip install -e fd-coding-law-bench-mcp`); verify `python -c "import langgraph, langchain_core"`.
- [x] 1.2 Create the package dir `fd_coding-law-bench-mcp/src/fd_coding_law_bench_mcp/pipeline/` (empty `__init__.py`).

## 2. DB tables + CRUD (`pipeline_runs`, `fill_cache`)

- [x] 2.1 Extend `ensure_schema` (or a new `src/eval/pipeline_store.py`) to `CREATE TABLE IF NOT EXISTS pipeline_runs (...)` and `CREATE TABLE IF NOT EXISTS fill_cache (...)` per the `Pipeline Runs Persistence` + `Fill Cache` requirements (columns enumerated there). Idempotent; no migration of existing tables.
- [x] 2.2 Add CRUD helpers: `insert_pipeline_run(row) -> id`, `list_pipeline_runs(limit) -> list[dict]`, `get_pipeline_run(id) -> dict|None`, and `get_or_create_fill(cache_key, ...) -> {fill_values, cache_id, hit}` / `lookup_fill(cache_key) -> dict|None`. Mirror the connection / `finally: conn.close()` style of `src/eval/store.py`.
- [x] 2.3 `pipeline_get` joins: fetch the `pipeline_runs` row, then `get_run(eval_run_id)` for criteria; raise `NotFoundError` on unknown id.
- [x] 2.4 Hermetic test (monkeypatch the DB connection) for `insert`/`list`/`get` and the fill-cache hit/miss path.

## 3. Small extensions to existing tools (additive, backward-compatible)

- [x] 3.1 `tools/generate.py`: add `custom_clause_ids: list[int] | None = None` to `contract_generate`; forward to `generate_contract_assembled(..., custom_clause_ids=custom_clause_ids)` (only when `stance`/`scenario` path is taken); return `body_text` (the assembled Markdown body). Keep the skeleton path unchanged.
- [x] 3.2 `tools/evaluate.py`: capture `run_id` from `store_result` (when `no_store=False`) and add it to the returned dict; `null` when `no_store=True`.
- [x] 3.3 Update `tests/test_generate_tool.py` / `tests/test_evaluate_tool.py` to cover `custom_clause_ids`, `body_text`, and `run_id`; assert backward-compatible defaults unchanged.

## 4. LLM fill node + `fill_cache`

- [x] 4.1 `pipeline/fill.py`: build the fill prompt from `contract_type`, `scenario`, and the slot `instructions` (`label`/`description`/`example`); call `DRAFTER_MODEL` via `litellm` (mirror `src/clauses/extract.py`, incl. the `LITELLM_MODEL_COST_MAP_URL` guard); parse JSON `{slot: value}`; substitute `{{slot}}` -> value into `body_text` (reuse `SLOT_PATTERN`); leave unfilled slots as `{{slot}}` and note them.
- [x] 4.2 `cache_key = sha1(contract_type | scenario | sorted(slots) | model | str(temperature))`; `lookup_fill` first; on miss, run the LLM and `insert` (recording `temperature`, `model`).
- [x] 4.3 Hermetic test: monkeypatch the LLM + `fill_cache` lookup; assert cache hit skips the LLM, cache miss calls it once and records `temperature`; assert all slots filled.

## 5. Self-heal `improve` node

- [x] 5.1 `pipeline/improve.py`: given failing `criteria_results` + per-section resolved clauses (via `clause_list` + the assembly resolution from `src.clauses.assemble._select_clauses`), prompt an LLM to emit structured JSON `{exclude_custom_clause_ids: [ids], recommendations: [{clause_id, action, reason}]}`. Validate the schema; on parse failure, emit empty actions (do not crash the loop).
- [x] 5.2 Apply only the per-run exclusion (feed `exclude_custom_clause_ids` into the next `generate` call's `custom_clause_ids`); append `recommendations` to state (never call `clause_review`).
- [x] 5.3 Hermetic test: monkeypatch the diagnosis LLM; assert a thin-override scenario yields an `exclude_custom_clause_ids` entry and a recorded recommendation, and that no `clause_review` is invoked.

## 6. LangGraph assembly

- [x] 6.1 `pipeline/graph.py`: define the `StateGraph` (state TypedDict per design D2) with nodes `generate`, `fill`, `evaluate`, `check`, `improve`, `store`; edges `START->generate->fill->evaluate->check`; conditional edge from `check` to `store` (terminal) when `all_pass or iteration>=max_iterations` else to `improve->generate`; `store` persists the best-scoring run.
- [x] 6.2 Wire `best` tracking: `check` compares the current run against `best` (by `n_passed` then `score`) and updates; `store` persists `best`.
- [x] 6.3 Graph-flow test with a stubbed LLM + MCP tool functions: (a) happy path stops at iteration 1 on `all_pass`; (b) failing path loops and stops at `max_iterations`, persisting the best run; (c) `actions_taken` / `recommendations` populated.

## 7. Rubric latest-version default

- [x] 7.1 `pipeline/` (or `src/eval/rubric.py`): `default_rubric(contract_type)` -> highest `vN` in `^contract_<type>_v(\d+)$`, else most-recent `created_at` among `contract_<type>_*`, else `None`. `pipeline_run` calls it when `rubric` is unset.
- [x] 7.2 Test: monkeypatch `list_rubrics`; assert sale -> `contract_sale_v2`, explicit override respected, missing -> error.

## 8. MCP tools + registration

- [x] 8.1 `tools/pipeline.py`: `pipeline_run`, `pipeline_list`, `pipeline_get` per the `Contract Pipeline Tools` requirement; import at call time; errors propagate.
- [x] 8.2 `server.py`: register `from .tools import pipeline as _pipeline`.
- [x] 8.3 Update `tests/test_server.py` `EXPECTED_TOOLS` and `tests/test_tools_registration.py` `EXPECTED_TOOLS` + `EXPECTED_TAGS` (tag `pipeline`) + `_TOOL_MODULES`.
- [x] 8.4 Hermetic `tests/test_pipeline.py` (monkeypatch the graph / MCP tool functions): `pipeline_run` returns `{pipeline_run_id, eval_run_id, score, ...}`; `pipeline_list` / `pipeline_get` round-trip; unknown id raises.

## 9. Validate + docs

- [x] 9.1 `cd fd-coding-law-bench-mcp && uv run pytest` - full suite green incl. registration exact-set + new pipeline tests.
- [x] 9.2 `openspec validate add-contract-pipeline`; fix any spec lint errors.
- [x] 9.3 Update `fd-coding-law-bench-mcp/README.md` tool table with the 3 pipeline tools + the `contract_generate` / `contract_evaluate` extensions.
- [x] 9.4 `/mcp` reconnect and smoke-test end-to-end on `sale` + `农产品买卖`: `pipeline_run` -> `pipeline_get`, confirm `pipeline_runs` row + linked eval, and that a failing sale run records the reject-420 recommendation (matching the earlier diagnosis) without mutating the clause DB.
