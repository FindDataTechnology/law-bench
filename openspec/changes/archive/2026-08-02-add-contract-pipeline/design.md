## Context

`fd-coding-law-bench-mcp` is a FastMCP server wrapping law-bench's `src.*` in place. It advertises generate / evaluate / rubric / prompt / compare / clause / law / search tools. Two pieces are missing for an end-to-end "generate -> fill -> evaluate -> persist with context" flow:

1. **No slot-fill**: `contract_generate` returns a DOCX skeleton with `{{slot}}` placeholders; `SlotInstruction` carries an `example` but nothing substitutes it. `contract_evaluate` reads a file as utf-8 text and fails on binary DOCX, so the contract must be filled text.
2. **No generation-context persistence**: `store_result` writes `eval_runs(contract_path, task_desc, draft_text, score, ...)`. `contract_evaluate` does not pass `draft_text` for standalone runs and records no `contract_type` / `tags` / `stance` / fill values, so `run_list` / `run_get` cannot reconstruct what was generated.

The assembly model (`src/clauses/assemble.py`) resolves one clause per section by `custom > tagged > base`, with tagged filtered by `scenario` and custom by `stance` + `is_assembly_ready`. A thin custom clause can override a rich base section (observed: sale custom id=420, 79 chars, overrode the 522-char base `权利义务` dropping inspection/warranty/ownership content). `generate_contract_assembled` already accepts `custom_clause_ids` to select a specific custom set - the lever the self-heal loop uses to exclude a thin override **per run** without mutating the shared DB.

Constraints (from the in-force `law-bench-mcp` spec):
- **Wrap-in-Place Without Relocation or Mutation** - import `src.*` in place; never copy or move.
- **Errors propagate** - wrapped `src` errors reach the MCP client as tool errors.
- Hermetic tests monkeypatch `src.*` / MCP tool functions (no DB / LLM / network).

## Goals / Non-Goals

**Goals:**
- One MCP call (`pipeline_run`) that produces an evaluated, persisted contract with full generation context, viewable later (`pipeline_list` / `pipeline_get`).
- Implement the orchestration as a **LangGraph** `StateGraph` (user requirement) whose nodes call the existing MCP tool functions (`contract_generate`, `contract_evaluate`) + a new LLM fill + a new store - hosted **inside** a new MCP tool (B+), so the graph both "calls MCP tools" and is itself exposed as an MCP tool.
- LLM slot-fill of **all** slots, scenario-aware, with a DB cache (`fill_cache`) keyed by input + model + temperature so identical inputs are deterministic and cheap; `temperature` + `model` recorded on every run.
- A self-healing loop that, on a failing eval, finds a passing clause configuration **per run** (via `custom_clause_ids` exclusion) and records recommended `clause_review` actions for human review - **not auto-applied** (option 3).
- rubric defaults to the latest version for the type.
- Keep wrap-in-place + error-propagation intact; the only `src/` touches are additive (two new tables via `ensure_schema`, no migration).

**Non-Goals:**
- Auto-applying `clause_review` recommendations (a human applies them; a follow-up may add `pipeline_apply_recommendations`).
- Persisting self-heal mutations to the shared clause DB (the loop is per-run only; recommendations are recorded, not executed).
- A streaming / HTTP transport; multi-tenant isolation; relocating `src/eval`.
- Beating LLM-judge non-determinism - the loop targets stable criteria, and `fill_cache` + `temperature=0` make the fill reproducible, but the judge (`kmodel_latest`) itself remains run-to-run noisy.

## Decisions

### D1 - Hosting: LangGraph inside a new MCP tool (B+)
The LangGraph `StateGraph` lives in `fd_coding_law_bench_mcp/pipeline/` and is invoked by the `pipeline_run` MCP tool. Graph nodes call the existing MCP tool **functions** (e.g. `from .tools.generate import contract_generate`) in-process - not via the MCP protocol - so "langgraph relies on calling MCP tools" is satisfied without a second process, an MCP client, or protocol round-trips. Rejected: a separate LangGraph service that is an MCP client (Option A) - adds lifecycle / multi-client / protocol overhead with no benefit here.

### D2 - Pipeline shape + state
```
START -> generate -> fill -> evaluate -> check ->(all_pass OR iter>=max)-> store -> END
                        ^                  |
                        |                  └─(fail)-> improve ─┘
                        └──────────────────┘
```
State (TypedDict) accumulates: `contract_type, tags, stance, rubric, task_desc, fill_mode, max_iterations, temperature, iteration, gen_result, body_text, filled_text, fill_values, fill_cache_id, eval_result, eval_run_id, best (result+state), actions_taken[], recommendations[]`. `check` picks the best-scoring run so far as the survivor; `store` persists the best, not necessarily the last.

### D3 - LLM fill: all slots, scenario-aware, cached, temperature recorded
The `fill` node:
1. computes `cache_key = sha1(contract_type | scenario | sorted(slots) | model | temperature)`;
2. `SELECT fill_values FROM fill_cache WHERE cache_key = ?` - on hit, reuse (skip LLM);
3. on miss, prompt the `DRAFTER_MODEL` (litellm, mirroring `src/clauses/extract.py`) for a JSON `{slot: value}` for **every** slot in the body (required + optional), grounded by `contract_type` + `scenario` + each `SlotInstruction.label/description/example`; substitute `{{slot}}` -> value into `body_text`; `INSERT INTO fill_cache`.
4. snapshot `fill_cache_id`, `fill_temperature`, `fill_values` onto the `pipeline_runs` row.
Default `temperature=0` for reproducibility; configurable per call.

### D4 - Self-heal: per-run exclusion + recorded recommendations (option 3)
The `improve` node (LLM) receives: failing `criteria_results`, the current filled contract, and the per-section resolved clauses (via `clause_list` + the assembly resolution). It emits a structured action:
- **applied (per-run, safe)**: `exclude_custom_clause_ids: [ids]` - forwarded to the next `contract_generate(custom_clause_ids=...)` so the rich base wins **for this pipeline run only**; the shared `clauses` table is untouched.
- **recorded (not applied)**: `recommendations: [{clause_id, action: "reject", reason}]` - persisted on `pipeline_runs.recommendations` for a human to apply later via `clause_review`.
The loop re-runs `generate -> fill -> evaluate` with the adjusted `custom_clause_ids`; `check` keeps the best score; capped at `max_iterations` (default 3). If a fix is found (`all_pass`) the loop stops early.

### D5 - rubric default = latest version
When `rubric` is unset: among rubrics whose name matches `^contract_<type>_v(\d+)$`, pick `max(vN)`; else fall back to the most recent `created_at` among `contract_<type>_*`; else raise a tool error.

### D6 - Persistence + viewing
- `pipeline_runs` row links `eval_run_id -> eval_runs.id` (the `contract_evaluate` run) and snapshots `fill_values` + `filled_text` + generation params + `actions_taken` + `recommendations` + best score.
- `pipeline_list(limit)` returns recent pipeline rows; `pipeline_get(pipeline_id)` returns the pipeline row + (via `run_get(eval_run_id)`) the per-criterion verdicts, so the whole run is reconstructable.

### D7 - Small additive extensions to existing tools
- `contract_generate(contract_type, format, tags, stance, out_dir, include_current_tags, custom_clause_ids=None)` - forwards `custom_clause_ids` to `generate_contract_assembled`; returns `body_text` (already computed internally). Backward-compatible.
- `contract_evaluate(...)` returns `run_id` (from `store_result`) alongside the existing fields.

## Risks / Mitigations

- **LLM-judge non-determinism** (`kmodel_latest` observed 4/10 <-> 6/10 on identical input): the loop targets **stable** criteria and keeps the best run; documented as a known limitation, not chased per-run.
- **LLM-fill non-determinism**: mitigated by `temperature=0` + `fill_cache` (same input -> same fill).
- **Self-heal side effects**: per-run `custom_clause_ids` exclusion touches no shared state; `recommendations` are recorded, not executed, so a bad LLM suggestion cannot corrupt the clause DB.
- **Cost / latency**: each iteration = 1 fill (cached after first) + 1 generate + 1 judge + 1 improve diagnosis. `fill_cache` amortizes fills; `max_iterations` caps the loop.
- **`body_text` exposure**: returning the assembled body is read-only and already materialized; no new writes.
