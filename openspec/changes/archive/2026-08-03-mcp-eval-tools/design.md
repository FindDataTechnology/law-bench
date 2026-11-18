## Context

`fd-coding-law-bench-mcp` is a FastMCP server (`fd_coding_law_bench_mcp`) that wraps law-bench's `src.*` modules in place. It currently advertises 5 tools: `generate_contract_from_tags`, `evaluate_contract`, `list_rubrics`, `list_runs`, `rag_search`. The `src/eval/` package is large (~2640 lines, 16 modules) and its public surface is far wider than the 3 functions the MCP wraps - rubric CRUD, criterion CRUD, prompt CRUD, compare orchestration + reads, law-info reads, and legal-refs extraction are reachable today only via CLIs (`python -m src.eval.run`, `python -m src.eval.compare`) or the FastAPI web app. An LLM agent operating on law-bench has no typed programmatic access to that surface, and `list_runs` returns run-level fields only (no way to fetch one run's `criteria_results`). `src/eval/` is imported by ~20 consumers (the web app, `src/contracts`, `src/clauses`, ~14 scripts), so it cannot be relocated.

Constraints (from the in-force `law-bench-mcp` spec):
- **Wrap-in-Place Without Relocation or Mutation** - import `src.*` from their on-disk locations; never copy or move them.
- **Errors propagate** - wrapped `src` errors reach the MCP client as tool errors; only `rag_search` degrades to `[]`.
- Hermetic tests - the existing MCP tests monkeypatch `src.*` (no DB / LLM / network).

## Goals / Non-Goals

**Goals:**
- Expose the full `src/eval` management surface as MCP tools (rubric/criterion/prompt CRUD, compare orchestration + reads, run detail, law-info/legal-refs reads), so an agent can operate the entire eval lifecycle without CLIs or the web UI.
- Optimise the existing evaluate tools: `list_rubrics` gains an optional `include_counts`; add `get_run_detail` to fetch a single run + its per-criterion verdicts.
- Keep wrap-in-place + error-propagation intact; the one `src/` touch is an additive read-only `get_run` helper.
- Test every tool (new + the existing 5) hermetically; add a registration smoke test that asserts the full expected tool set is advertised and each tool imports + dispatches; fix any tool that does not work.

**Non-Goals:**
- Physically relocating `src/eval` into the MCP package (rejected - breaks ~20 consumers; forbidden by the in-force spec).
- Exposing `harbor_seed.py` / `seed/` seeder scripts over MCP (bulk write machinery, not the evaluate engine; risky as an agent-callable tool).
- Law-info / clause **writes** over MCP (read-only this change; seeding stays a script).
- Auth / multi-tenant; a streaming transport; LLM-judge quality changes (the judge is wrapped unchanged).

## Decisions

### 1. Wrap-in-place, not relocate
"Move all evaluate code to the MCP as tools" is interpreted as **expose** the `src/eval` surface as MCP tools, not physically move the package. Relocation would break the web app, `src/contracts`, `src/clauses`, and ~14 scripts that import `src.eval`, and violates the in-force Wrap-in-Place requirement. *Alternative considered*: physically move `src/eval` under `fd-coding-law-bench-mcp/` and re-export - rejected for the blast radius above.

### 2. Tool module layout (one module per concern)
New modules mirror the existing `tools/{generate,evaluate,rag}.py` split:
- `tools/rubrics.py` - rubric + criterion CRUD (criterion lives with its rubric; tightly coupled).
- `tools/prompts.py` - prompt CRUD.
- `tools/compare.py` - compare orchestration + reads (`run_compare`, `list_compares`, `get_compare`, `get_compare_matrix`, `get_run_draft`).
- `tools/law_info.py` - law-info reads + legal-refs extraction.
- `tools/evaluate.py` - extended: `list_rubrics` `include_counts` + new `get_run_detail`.

`server.py` imports each module so `@mcp.tool` decorators register (order irrelevant). *Alternative*: a single `tools/eval.py` - rejected (readability, test isolation, matches the one-module-per-concern convention).

### 3. Deferred `src.*` imports at call time
Each tool imports its `src.eval.*` dependency inside the function body (as `evaluate.py` already does), keeping server startup light and avoiding import-time coupling to DB / deepeval / crewai.

### 4. Error propagation: raise, do not swallow
CRUD tools let `ManageError` (`NotFoundError` / `ConflictError` / `ValidationError` / `HarborReadOnlyError`) and `KeyError` / `ValueError` propagate. FastMCP surfaces a raised exception to the client as a tool error, satisfying the in-force "errors reach the client" contract. *Alternative*: catch and return an `{error: ...}` dict - rejected (breaks the contract, hides failures from the agent, untestable as errors). `rag_search` keeps its `[]`-on-failure path unchanged.

### 5. `get_run` additive helper in `src/eval/store.py`
`get_run_detail` needs a single run + its `criteria_results`; `store.py` has no such read (only `list_runs` for run-level fields and `get_compare` for runs-under-a-compare). Add `get_run(run_id, db_path=DEFAULT_DB) -> dict` to `store.py` - read-only, mirrors `get_compare`'s per-run criteria fetch, no schema change. This is the only `src/` modification. *Alternative*: duplicate the SQL in the MCP - rejected (logic duplication, drift risk). *Alternative*: fetch via `get_compare` only - rejected (cannot reach standalone runs not grouped under a compare).

### 6. `run_compare` resolves prompt **names**, not records
The MCP `run_compare` accepts `prompt_names: list[str]` and resolves them to records via `compare.load_prompts` inside the tool, then calls `compare.run_compare`. The agent passes names (simpler, matches the CLI `--prompts` shape); records are an internal detail. `draft_fn` / `judge` stay injectable on the wrapped `src.eval.compare.run_compare` (the MCP uses defaults - real DRAFTER + real judge).

### 7. `get_compare_matrix` convenience tool
`get_compare_matrix(compare_id)` = `store.get_compare` + `compare.build_matrix` in one call, returning the criteria × prompts matrix. Avoids a second round-trip for the common "show me the matrix" query. *Alternative*: force two calls - rejected (needless latency).

### 8. Harbor read-only is inherited, not re-implemented
`src.eval.rubric_crud` already raises `HarborReadOnlyError` on any write to a harbor rubric. The MCP tools do not add a second guard - they let it propagate as a tool error. No new logic, no drift.

### 9. Test strategy = hermetic per-tool + registration smoke + regression
- One hermetic test file per new module (`test_rubrics.py`, `test_prompts.py`, `test_compare.py`, `test_law_info.py`), monkeypatching `src.eval.*` exactly as `test_evaluate_tool.py` does - covering happy path + each error class (NotFound / Conflict / Validation / HarborReadOnly).
- `test_tools_registration.py`: import `mcp`, introspect the registered tool names, assert the exact expected 27-tool set is present (catches a mis-named or unregistered `@mcp.tool`); smoke-import each tool module to confirm no import-time error.
- Re-run the existing `test_{generate,evaluate,rag,server}.py` to confirm the 5 original tools still register and pass (regression).
"Test every tool, fix what's broken" is satisfied by this suite: any tool that fails to register, mis-dispatches, or swallows an error is caught and fixed in-iteration.

## Risks / Trade-offs

- **[Large surface = more to maintain]** 27 tools across 6 modules. -> Mitigation: one hermetic test per module + the registration smoke test pinning the exact tool set; shared monkeypatch pattern from `test_evaluate_tool.py`.
- **[`run_compare` is expensive]** It makes LLM draft calls + one judge call per draft. -> Mitigation: it is an explicit agent action; `n_drafts` defaults to 1; cost is documented in the tool docstring; errors propagate (no silent hang).
- **[CRUD tools mutate the eval DB]** Rubric/prompt/criterion writes change shared state. -> Mitigation: harbor read-only guard is inherited; `ManageError` (Conflict/Validation) surfaces clearly; every write takes an explicit id or unique name; destructive ops (`delete_*`) take an explicit id. No bulk destructive tool.
- **[`get_run` touches shared `src/eval/store.py`]** -> Mitigation: additive, read-only, no schema change, mirrors `get_compare`; covered by the existing `test-suite` spec + a new MCP test asserting shape + NotFound on unknown id.
- **[Tool registration drift]** A renamed/mis-decorated tool would silently disappear. -> Mitigation: the registration smoke test asserts the exact expected set, failing CI on drift.

## Migration Plan

- **No data migration** - the schema is idempotent `CREATE TABLE IF NOT EXISTS`; `get_run` adds no columns/tables.
- **Deploy**: `uv pip install -e ./fd-coding-law-bench-mcp` (already editable; new modules picked up), then restart `python -m fd_coding_law_bench_mcp`. Clients auto-discover the new tools via the MCP tool list.
- **Rollback**: revert the package commit; remove `get_run` from `store.py` (it is additive and unused outside the MCP, so removal is safe). No data to restore.

## Open Questions

- **`run_compare` input shape** - names only, or also accept pre-resolved records for advanced callers? Decision: names only this change; records remain an internal detail.
- **Expose law-info / clause writes later?** Decision: no - read-only this change; seeding stays a script. Revisit if an agent needs to seed from MCP.
