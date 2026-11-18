## 1. Additive `get_run` read helper in `src/eval/store.py`

- [x] 1.1 Add `get_run(run_id: int, db_path=DEFAULT_DB) -> dict` to `src/eval/store.py`: call `ensure_schema(db_path)`, then `SELECT id, rubric_name, contract_path, task_desc, score, max_score, all_pass, n_criteria, n_passed, summary, judge_model, scored_at, compare_run_id, prompt_name, prompt_type, variant_label FROM eval_runs WHERE id = %s`; if absent raise `KeyError(f"Run not found: {run_id}")`; then `SELECT criterion_id, title, verdict, reasoning, ordinal FROM eval_criteria_results WHERE run_id = %s ORDER BY ordinal`; return `{**dict(run_row), "criteria_results": [dict(c) for c in crits]}`. Mirror the connection/`finally: conn.close()` style of `get_compare`.
- [x] 1.2 Add a hermetic test to `tests/test_store.py`: an existing run returns the run-level fields plus an ordered `criteria_results`; an unknown `run_id` raises `KeyError`. Verified against the live remote Postgres (`23.144.68.246:15432`).

## 2. Rubric & criterion management tools (`tools/rubrics.py`)

- [x] 2.1 Create `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/tools/rubrics.py` with `@mcp.tool` functions delegating to `src.eval.rubric_crud` (imported at call time): `get_rubric(name)` -> `get_rubric_detail`; `create_rubric(name, context, description=None, criteria=None)`; `update_rubric(rubric_id, name, context, description=None)`; `delete_rubric(rubric_id)`; `add_criterion(rubric_id, name, description, guidance)`; `update_criterion(criterion_id, name, description, guidance)`; `delete_criterion(criterion_id)`; `reorder_criteria(rubric_id, ordered_criterion_ids)`.
- [x] 2.2 Let `ManageError` (`NotFoundError`/`ConflictError`/`ValidationError`/`HarborReadOnlyError`) propagate as tool errors; do not swallow. For `delete_rubric`/`delete_criterion`, return `{deleted: True, id: <id>}` (the wrapped functions return `None`).
- [x] 2.3 Create `fd-coding-law-bench-mcp/tests/test_rubrics.py` (monkeypatch `src.eval.rubric_crud`): `get_rubric` returns detail + ordered criteria; `create_rubric` with criteria round-trips; `update_rubric` on a harbor rubric raises `HarborReadOnlyError`; `reorder_criteria` with a mismatched id set raises `ValidationError`; `delete_rubric` returns the ack and delegates the id.

## 3. Prompt management tools (`tools/prompts.py`)

- [x] 3.1 Create `tools/prompts.py` with `@mcp.tool` functions delegating to `src.eval.prompt_crud` (imported at call time): `list_prompts()`; `get_prompt(name)`; `create_prompt(name, contract_type, purpose, content, description=None, prompt_type=None)`; `update_prompt(prompt_id, name, contract_type, purpose, content, description=None, prompt_type=None)`; `delete_prompt(prompt_id)`.
- [x] 3.2 Let `NotFoundError`/`ConflictError`/`ValidationError` propagate as tool errors. `delete_prompt` returns `{deleted: True, id: <id>}`.
- [x] 3.3 Create `fd-coding-law-bench-mcp/tests/test_prompts.py` (monkeypatch `src.eval.prompt_crud`): `list_prompts` returns rows without `content`; `get_prompt` returns the full record incl. `content`; `create_prompt` then `get_prompt` round-trips; `delete_prompt` on an unknown id raises `NotFoundError`.

## 4. Compare tools (`tools/compare.py`)

- [x] 4.1 Create `tools/compare.py` with `@mcp.tool` functions: `run_compare(contract_type, rubric_name, task_desc, prompt_names, n_drafts=1, label=None)` -> `src.eval.compare.load_prompts(prompt_names)` then `src.eval.compare.run_compare(...)` unchanged; `list_compares(limit=20)` -> `src.eval.store.list_compares`; `get_compare(compare_id)` -> `src.eval.store.get_compare`; `get_compare_matrix(compare_id)` -> `src.eval.compare.build_matrix(src.eval.store.get_compare(compare_id))`; `get_run_draft(compare_id, run_id)` -> `src.eval.store.get_run_draft`. Import at call time.
- [x] 4.2 Let `NotFoundError`/`ValidationError`/`KeyError` propagate as tool errors.
- [x] 4.3 Create `fd-coding-law-bench-mcp/tests/test_compare.py` (monkeypatch `src.eval.compare` + `src.eval.store`): `run_compare` with one prompt name raises `ValidationError` and persists nothing; `list_compares` returns recent rows; `get_compare` on an unknown id raises `KeyError`; `get_compare_matrix` returns `{criteria, columns, cells, n_drafts}`.

## 5. Law-info & legal-refs tools (`tools/law_info.py`)

- [x] 5.1 Create `tools/law_info.py` with `@mcp.tool` functions (read-only, import at call time): `list_law_info_types()` -> `src.eval.law_info.list_law_info_types`; `get_law_info(contract_type)` -> `src.eval.law_info.get_law_info`; `extract_legal_references()` -> `src.eval.legal_refs.extract_references(src.eval.law_info.all_law_info())`.
- [x] 5.2 Let `NotFoundError` propagate as a tool error.
- [x] 5.3 Create `fd-coding-law-bench-mcp/tests/test_law_info.py` (monkeypatch `src.eval.law_info` + `src.eval.legal_refs`): `list_law_info_types` returns `{key, zh_name, sources}`; `get_law_info` on an unknown type raises `NotFoundError`; `extract_legal_references` returns categorized laws sorted by category then name.

## 6. Optimise existing evaluate tools (`tools/evaluate.py`)

- [x] 6.1 Extend `list_rubrics` with an optional `include_counts: bool = False`: when `True` delegate to `src.eval.rubric_crud.list_rubrics_with_counts` (rows carry `id`, `criterion_count`, `is_harbor`); when `False` keep the current `src.eval.rubric.list_rubrics` behavior (backward compatible).
- [x] 6.2 Add `get_run_detail(run_id: int) -> dict` delegating to `src.eval.store.get_run` (from task 1.1); let `KeyError` propagate as a tool error.
- [x] 6.3 Extend `fd-coding-law-bench-mcp/tests/test_evaluate_tool.py`: `list_rubrics(include_counts=True)` returns enriched rows (monkeypatch `rubric_crud.list_rubrics_with_counts`); `get_run_detail` returns run fields + `criteria_results` and an unknown id raises `KeyError` (monkeypatch `store.get_run`).

## 7. Server wiring (`server.py`)

- [x] 7.1 In `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/server.py`, import the new tool modules (`rubrics`, `prompts`, `compare`, `law_info`) alongside the existing `evaluate`/`generate`/`rag` imports so their `@mcp.tool` decorators register.
- [x] 7.2 Verify importability + registration: `uv run python -c "from fd_coding_law_bench_mcp.server import mcp; ..."` lists all 27 tools (verified via FastMCP `Client.list_tools()`).

## 8. Tests: registration smoke + regression

- [x] 8.1 Create `fd-coding-law-bench-mcp/tests/test_tools_registration.py`: import `mcp`, introspect the registered tool names, and assert the set equals the expected 27 tools; smoke-import each `tools/*` module to confirm no import-time error.
- [x] 8.2 Update `fd-coding-law-bench-mcp/tests/test_server.py`'s expected tool list from 5 to the full 27-tool set (exact `==` assertion); confirm the existing introspection approach still passes.
- [x] 8.3 Run `uv run pytest fd-coding-law-bench-mcp/tests -q` (41 passed) and `uv run pytest tests/test_store.py -q` (12 passed, incl. live Postgres); all pass. Also fixed a pre-existing broken tool test found in-iteration: `test_generate_tool.py::test_include_current_tags_returns_vocab_with_temp_dim` was stale vs. the current `register_tag_dim(contract_type, name, ...)` signature and the nested `TAG_VOCAB`; aligned `tools/generate.py` `current_tags` to the spec's flat per-type vocab (`tag_vocab_for_type`) and fixed the test's `register_tag_dim` call.

## 9. Verification, docs, openspec validate

- [x] 9.1 Update `fd-coding-law-bench-mcp/README.md` tool table with the new tools (grouped: rubric/criterion, prompt, compare, law-info) and the `list_rubrics` `include_counts` / `get_run_detail` notes.
- [x] 9.2 `openspec validate mcp-eval-tools --strict` -> valid.
- [x] 9.3 Confirm scope of `src/` changes: this change's only `src/` edit is the additive `get_run` in `src/eval/store.py`; the new tool modules + tests + README + the `openspec/changes/mcp-eval-tools/` change are the rest. (Note: the working tree also shows unrelated concurrent edits - `src/contracts/data/contracts.json`, `src/eval/law_refined_citations.py`, `src/eval/seed/law_info/*.md`, `tests/test_{contract_templates,law_info}.py`, and 4 auto-archived `add-clause-*`/`unify-clause-tags` changes - none belong to this change.)
- [ ] 9.4 (Deferred / live-env) Manual end-to-end of the full tool chain against the Ark LLM judge (`create_rubric` -> `get_rubric`; `evaluate_contract` -> `get_run_detail`; `run_compare` -> `get_compare_matrix`). Hermetic MCP tests + the live-Postgres `get_run`/store tests cover correctness offline; the Ark-judge path is the remaining live check.
