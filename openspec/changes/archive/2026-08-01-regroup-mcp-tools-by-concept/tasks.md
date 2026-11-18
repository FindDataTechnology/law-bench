## 1. Verify inventory

- [x] 1.1 Re-grep `@mcp.tool` across `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/tools/` and confirm the 27-tool inventory matches the design map (catch any drift from landed `mcp-eval-tools` / `replace-region-with-scenario`).
- [x] 1.2 Confirm FastMCP `@mcp.tool` accepts a `tags=` kwarg in the installed version (fastmcp 3.4.5; `@mcp.tool` returns the original callable function, so `tags=` is safe for direct-call tests).

## 2. Rename + tag existing tools

- [x] 2.1 `tools/generate.py`: rename `generate_contract_from_tags` -> `contract_generate`, add `tags={"contracts"}`.
- [x] 2.2 `tools/evaluate.py`: rename `evaluate_contract` -> `contract_evaluate` (tag `contracts`), `list_rubrics` -> `rubric_list` (tag `rubrics`), `list_runs` -> `run_list` (tag `eval`), `get_run_detail` -> `run_get` (tag `eval`).
- [x] 2.3 `tools/rubrics.py`: rename `get/create/update/delete_rubric` -> `rubric_get/create/update/delete` (tag `rubrics`); rename `add/update/delete_criterion`, `reorder_criteria` -> `criterion_add/update/delete/reorder` (tag `rubrics`).
- [x] 2.4 `tools/prompts.py`: rename `list/get/create/update/delete_prompt` -> `prompt_list/get/create/update/delete` (tag `prompts`).
- [x] 2.5 `tools/compare.py`: rename `run_compare` -> `compare_run`, `list_compares` -> `compare_list`, `get_compare` -> `compare_get`, `get_compare_matrix` -> `compare_matrix`, `get_run_draft` -> `run_draft` (all tag `eval`).
- [x] 2.6 `tools/law_info.py`: rename `list_law_info_types` -> `law_types`, `get_law_info` -> `law_info`, `extract_legal_references` -> `law_references` (all tag `law`).
- [x] 2.7 `tools/rag.py`: rename `rag_search` -> `search_clauses` (tag `search`).

## 3. Add new tag tools (read-only)

- [x] 3.1 Create `tools/tags.py` with `tag_vocab_list(contract_type=None)` wrapping `src.clauses.tags.tag_vocab_for_type`, tagged `tags`.
- [x] 3.2 Add `tag_validate(tags, contract_type=None)` wrapping `src.clauses.tags.validate_tags` (let `ValueError` propagate as a tool error), tagged `tags`.
- [x] 3.3 Register the new module in `server.py` (add `from .tools import tags as _tags`).

## 4. Update tests

- [x] 4.1 `tests/test_generate_tool.py`: updated to `contract_generate` (replace_all - no src-patch name collision).
- [x] 4.2 `tests/test_evaluate_tool.py`: updated `evaluate_contract`->`contract_evaluate`, `list_rubrics`->`rubric_list`, `list_runs`->`run_list`, `get_run_detail`->`run_get` (preserved `src.*` patch strings).
- [x] 4.3 `tests/test_rag_tool.py`: updated `rag_search` -> `search_clauses`.
- [x] 4.4 `tests/test_rubrics.py`: updated rubric/criterion tool imports+calls (preserved `src.eval.rubric_crud` patch strings).
- [x] 4.5 `tests/test_prompts.py`: updated prompt tool imports+calls (preserved `src.eval.prompt_crud` patch strings).
- [x] 4.6 `tests/test_compare.py`: updated compare/run tool imports+calls (preserved `src.eval.compare`/`store` patch strings).
- [x] 4.7 `tests/test_law_info.py`: updated `list_law_info_types`->`law_types`, `get_law_info`->`law_info`, `extract_legal_references`->`law_references` (preserved `src.eval.law_info`/`legal_refs` patch strings).
- [x] 4.8 `tests/test_tools_registration.py`: updated `EXPECTED_TOOLS` to the 29 new names; added `EXPECTED_TAGS` + `test_each_tool_carries_its_concept_tag` (reads `meta.fastmcp.tags`); added `tools.tags` to `_TOOL_MODULES`.
- [x] 4.9 `tests/test_server.py`: updated `EXPECTED_TOOLS` to the 29 new names.
- [x] 4.10 `tests/test_tags.py` (new): covers `tag_vocab_list` (load-before-read + universal-only) and `tag_validate` (cleaned dict + invalid-value propagation).

## 5. Update docs

- [x] 5.1 `README.md`: rewrote the tool table regrouped by the 7 concepts; documented the concept grouping (names + `tags=`/`meta.fastmcp.tags`); added the read-only `tags` group; noted the breaking rename.
- [x] 5.2 Added an old -> new migration table to README for callers.

## 6. Verify

- [x] 6.1 `uv run pytest fd-coding-law-bench-mcp/tests` - 47 passed (42 baseline + 5 new).
- [x] 6.2 Launched the server in-process; `tools/list` advertises 29 tools, each carrying its concept tag in `meta.fastmcp.tags`, grouped into the 7 concepts (contracts 2 / rubrics 9 / prompts 5 / eval 7 / search 1 / law 3 / tags 2).
- [x] 6.3 Spot-checked `tag_vocab_list`, `tag_validate`, and `search_clauses` invoke correctly (tag tools delegate + load-first; search returns 5 chunks / degrades to `[]`).
