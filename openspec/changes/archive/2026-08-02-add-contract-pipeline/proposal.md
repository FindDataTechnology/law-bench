## Why

The law-bench MCP exposes `contract_generate` and `contract_evaluate` as **separate** tools, but there is no end-to-end flow that takes a contract type / tags and produces an evaluated, persisted contract with full generation context. Today an operator must:

1. call `contract_generate` (returns a DOCX skeleton with `{{slot}}` placeholders - **no fill capability exists**);
2. manually convert DOCX -> text and fill the slots by hand (`contract_evaluate` reads files as utf-8 text and chokes on binary DOCX);
3. call `contract_evaluate`, which stores an `eval_runs` row carrying only `contract_path` / `task_desc` / `draft_text` - **the generation context (contract_type, tags, stance, filled slot values) is lost**, and `contract_evaluate` does not even populate `draft_text` for standalone runs;
4. re-view via `run_list` / `run_get`, which cannot show what was generated or how.

This change adds a **LangGraph-driven pipeline** exposed as MCP tools: `generate -> fill (LLM, scenario-aware, cached) -> evaluate -> self-heal (per-run clause exclusion + recorded review recommendations) -> persist` to a new `pipeline_runs` table with full context, viewable via `pipeline_list` / `pipeline_get`. It also closes two small gaps in the existing tools so the graph can drive them: `contract_generate` returns the body text and accepts `custom_clause_ids`; `contract_evaluate` returns the stored `run_id`.

## What Changes

- **New MCP tools** (`fd_coding_law_bench_mcp/tools/pipeline.py`, concept tag `pipeline`): `pipeline_run`, `pipeline_list`, `pipeline_get` - mirroring the `compare_run` / `compare_list` / `compare_get` shape.
- **New LangGraph module** (`fd_coding_law_bench_mcp/pipeline/`): a `StateGraph` with nodes `generate -> fill -> evaluate -> check -> (improve) -> store`. v1 includes the self-healing loop. Nodes call the existing MCP tool functions (`contract_generate`, `contract_evaluate`) plus a new LLM fill node and a new pipeline store - honoring "langgraph relies on calling MCP tools" while being hosted inside a new MCP tool (B+).
- **New DB tables** (idempotent `CREATE TABLE IF NOT EXISTS` via `ensure_schema`, same `law_bench` Postgres):
  - `pipeline_runs` - generation context (contract_type, tags, stance, rubric_name, task_desc, fill_mode, fill_values, filled_text, eval_run_id, score, n_passed, n_criteria, all_pass, actions_taken, recommendations, iteration, fill_cache_id, fill_temperature, created_at).
  - `fill_cache` - LLM fill-result cache keyed by `hash(contract_type, scenario, slots_sorted, model, temperature)` so identical inputs reuse a prior fill (determinism + cost); stores `fill_values`, `temperature`, `model`, `created_at`.
- **LLM slot-fill**: fills **all** slots (required + optional) with scenario-aware values via the `DRAFTER_MODEL` (litellm, mirroring `src/clauses/extract.py`); `temperature` configurable (default 0); results cached in `fill_cache`; `temperature` + `model` recorded on every `pipeline_runs` row.
- **Self-healing loop (option 3 scope)**: on a failing eval, an `improve` node (LLM diagnosis over failing criteria + per-section resolved clauses via `clause_list`) decides a **per-run** action - exclude specific custom clause ids (passed to `contract_generate` as `custom_clause_ids`) so the rich base can win **without mutating the shared DB**. The same diagnosis also emits **recommended** `clause_review` actions (e.g. reject clause X) recorded on the `pipeline_runs` row for human one-click apply - **not auto-executed**. The loop keeps the best-scoring run across iterations and is capped by `max_iterations` (default 3).
- **Rubric default**: when `rubric` is not passed, select the **latest version** for the contract type - highest trailing `v<N>` among `contract_<type>_v*` rubrics, falling back to most recent `created_at`; error if none.
- **Small extensions to existing tools** (additive, backward-compatible):
  - `contract_generate`: accept an optional `custom_clause_ids: list[int]` (forwarded to `generate_contract_assembled` so the loop can exclude thin custom clauses per-run); return `body_text` (the assembled Markdown body, already computed internally) so the fill node avoids a DOCX round-trip.
  - `contract_evaluate`: return `run_id` (the id from `store_result`) so the pipeline can foreign-key `pipeline_runs.eval_run_id`.
- **Dependencies**: add `langgraph` + `langchain-core` to the MCP package `pyproject.toml` (and the shared law-bench venv).
- **Tests**: hermetic unit tests for the new tools and the fill/improve nodes (monkeypatch MCP tool functions + LLM, mirroring `test_rubrics.py`); a registration smoke test update (expected tool set gains `pipeline_run` / `pipeline_list` / `pipeline_get`); a graph-flow test with a stubbed LLM asserting the loop terminates at `all_pass` or `max_iterations` and records recommendations.

## Capabilities

### New Capabilities
- `contract-pipeline`: the LangGraph generate -> fill -> evaluate -> self-heal pipeline, the `fill_cache` (LLM fill cache with recorded temperature), and the `pipeline_runs` persistence + viewing.

### Modified Capabilities
- `law-bench-mcp`: add the `pipeline_run` / `pipeline_list` / `pipeline_get` tools; extend `contract_generate` (`custom_clause_ids` + `body_text`) and `contract_evaluate` (`run_id`); require the pipeline tools to delegate to a LangGraph whose nodes call the existing MCP tool functions.

## Impact

- **New code**: `fd_coding-law-bench-mcp/src/fd_coding_law_bench_mcp/pipeline/{graph,nodes,fill,store}.py`; `tools/pipeline.py`; `tests/test_pipeline.py` (+ update `tests/test_server.py` / `tests/test_tools_registration.py` expected sets).
- **Modified code**: `tools/generate.py` (`custom_clause_ids` + `body_text`), `tools/evaluate.py` (`run_id`), `server.py` (register `pipeline`), `src/eval/store.py` (or a new `src/eval/pipeline_store.py`) for `pipeline_runs` / `fill_cache` schema + CRUD (read-mostly from the MCP side).
- **Dependencies**: `langgraph`, `langchain-core` (new).
- **Operations**: restart `python -m fd_coding_law_bench_mcp` to load the new tools; `ensure_schema` creates the two new tables on first run (no manual migration).
- **Out of scope**: auto-applying the recommended `clause_review` actions (recommendations are recorded only - a human applies them, or a follow-up change adds a `pipeline_apply_recommendations` tool); HTTP/SSE transport for the MCP; multi-tenant isolation; a streaming transport.
