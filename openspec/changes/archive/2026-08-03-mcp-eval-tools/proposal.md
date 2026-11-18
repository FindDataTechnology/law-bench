## Why

The `fd-coding-law-bench-mcp` server exposes only 3 of `src/eval`'s ~25 public functions - `evaluate_contract`, `list_rubrics`, `list_runs`. An LLM agent can score a draft and list rubrics/runs, but it cannot inspect or build a rubric, edit criteria, manage drafting prompts, fetch a single run's per-criterion verdicts, or run a prompt-comparison experiment without shelling out to CLIs (`python -m src.eval.run`, `python -m src.eval.compare`) or driving the web UI. The evaluation subsystem needs a complete, typed MCP surface so the agent can operate the full rubric / prompt / run / compare lifecycle programmatically - and the existing tools have a read gap (`list_runs` returns run-level fields only; there is no way to fetch one run's `criteria_results`). This change exposes the rest of the eval surface (wrap-in-place, no relocation), optimises the existing tools to close the read gap, and adds hermetic tests for every tool - fixing any that do not work.

## What Changes

- **New MCP tool modules wrapping the rest of `src/eval`** (in-place import; no relocation, consistent with the in-force Wrap-in-Place requirement):
  - **Rubric & criterion CRUD** (`tools/rubrics.py`): `get_rubric`, `create_rubric`, `update_rubric`, `delete_rubric`, `add_criterion`, `update_criterion`, `delete_criterion`, `reorder_criteria` - wrapping `src.eval.rubric_crud`. Harbor rubrics stay read-only; the `ManageError` hierarchy (`NotFoundError` / `ConflictError` / `ValidationError` / `HarborReadOnlyError`) surfaces as tool errors, never swallowed.
  - **Prompt CRUD** (`tools/prompts.py`): `list_prompts`, `get_prompt`, `create_prompt`, `update_prompt`, `delete_prompt` - wrapping `src.eval.prompt_crud` (always editable, no harbor guard).
  - **Compare orchestration + reads** (`tools/compare.py`): `run_compare` (resolve prompt names -> draft + evaluate each -> persist grouped), `list_compares`, `get_compare`, `get_compare_matrix` (compare + `build_matrix`), `get_run_draft` - wrapping `src.eval.compare` + `src.eval.store`.
  - **Law-info & legal-refs reads** (`tools/law_info.py`): `list_law_info_types`, `get_law_info`, `extract_legal_references` - wrapping `src.eval.law_info` + `src.eval.legal_refs` (read-only).
- **Optimise existing tools** (`tools/evaluate.py`): `list_rubrics` gains an optional `include_counts: bool` (wraps `list_rubrics_with_counts`, backward-compatible default); add `get_run_detail(run_id)` to fetch a single run + its `criteria_results`. The latter requires one small additive read helper `get_run(run_id)` in `src/eval/store.py` - the only `src/` change, read-only, no schema change.
- **Errors propagate**: every wrapped `src.eval` call's `ManageError` / `KeyError` / `ValueError` reaches the MCP client as a tool error rather than being silently swallowed (mirrors the existing Wrap-in-Place error contract; `rag_search` keeps its `[]`-on-failure path).
- **Test every tool, fix what's broken**: hermetic unit tests for each new tool (monkeypatch `src.eval`, mirroring `test_evaluate_tool.py`); a registration/introspection smoke test asserting the full expected tool set is advertised and each tool imports + dispatches without error; regression-verify the existing 5 tools still pass. Any tool that fails is fixed.
- **Docs**: update `fd-coding-law-bench-mcp/README.md` tool table and the `law-bench-mcp` spec to cover the new surface.

## Capabilities

### New Capabilities
<!-- None. All new tools extend the existing law-bench-mcp capability; the surface change is captured as a modification below. -->

### Modified Capabilities
- `law-bench-mcp`: extend the MCP tool surface from 5 tools to the full `src/eval` lifecycle - rubric/criterion CRUD, prompt CRUD, compare orchestration + reads, single-run detail, law-info/legal-refs reads - plus an `include_counts` option on `list_rubrics` and a new `get_run_detail` tool. Adds wrap-in-place + error-propagation requirements for the new CRUD tools, and a requirement that every advertised tool be covered by a hermetic test.

## Impact

- **New code**: `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/tools/{rubrics,prompts,compare,law_info}.py`; tests `fd-coding-law-bench-mcp/tests/test_{rubrics,prompts,compare,law_info,tools_registration}.py`; `server.py` imports the new modules so their `@mcp.tool` decorators register.
- **Modified code**: `tools/evaluate.py` (`list_rubrics` `include_counts` + new `get_run_detail`); `src/eval/store.py` (additive `get_run(run_id)` read helper - read-only, no schema change); `fd-coding-law-bench-mcp/README.md`.
- **Dependencies**: none new - reuses `fastmcp`, `psycopg`, `deepeval` already in the shared law-bench venv.
- **No relocation** of `src/eval`: it is imported by ~20 consumers (the web app, `src/contracts`, `src/clauses`, ~14 scripts); wrap-in-place per the in-force spec requirement.
- **Operations**: restart `python -m fd_coding_law_bench_mcp` to pick up the new tools; no DB migration (schema is idempotent `CREATE TABLE IF NOT EXISTS`).
- **Out of scope**: physically relocating `src/eval` into the MCP package; exposing `harbor_seed.py` / `seed/` seeder scripts (bulk write machinery, not the evaluate engine); auth/multi-tenant; a streaming transport.
