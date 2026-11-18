## Context

`law-template` drafts Chinese contracts with a CrewAI crew (`src/crew.py`: intake_clarifier → drafter → auditor → revise) and evaluates a drafted contract against a rubric with `src/eval/scoring.py::evaluate_contract` - deepeval GEval, one binary pass/fail judge call per criterion, all-pass scoring. Runs are persisted by `src/eval/store.py` to `eval_runs` + `eval_criteria_results` in `db/evaluation_rules.db`, snapshotted as text (rubric name, contract path, task) so a run survives later rubric edits.

The completed `chinese-rubrics-and-prompt-management` change added a `prompts` table (per-contract-type drafting prompts, `source = local`, always editable) with full CRUD and a management UI. It explicitly left two follow-ups: (1) wiring the crew to read prompts at runtime, and (2) any consumption of prompts. The `prompts` table is therefore stored but not yet consumed by anything.

Consequence: an `eval_runs` row knows *which rubric* judged a draft and *which file* held it, but **not which prompt produced the draft**, and nothing groups runs into a comparison. There is no grounded way to answer "did revising this drafting prompt make drafts score better." This change closes that gap with an end-to-end prompt compare.

The 19 seeded prompts (`draft_<type>`) each carry a single Chinese paragraph of drafter instruction ("起草一份买卖合同。须包含：…"). Their content shape is a drafter instruction, which matters for the generation-mode decision below.

## Goals / Non-Goals

**Goals:**
- Compare N ≥ 2 prompts for a fixed area (contract_type + rubric + task) by generating a draft with each and running the real judge on each.
- Persist compares as a grouped, queryable record (a `compare_run` owning its `eval_runs`), snapshotted so history survives prompt/rubric edits.
- Render a per-criterion matrix (criteria × prompts) that makes prompt differences visible, since the all-pass run score is non-discriminating.
- Add a `prompt_type` (variant/lineage) tag to prompts so compare columns are legible (`baseline` vs `experimental`).
- Mirror compare state to browser `localStorage` (WIP form + compact results) for instant, refresh-surviving review.
- Reuse `evaluate_contract` unchanged; add orchestration, not new eval logic.

**Non-Goals:**
- Full-crew generation mode (audit+revise mask the drafter-level differences a compare measures; follow-up).
- Auto-mutating a base prompt into variants (users author variants via existing prompt CRUD).
- Wiring the production crew to consume `prompts` at runtime (separate prior follow-up; drafter-only compare uses a direct LLM call, not the crew).
- IndexedDB client storage (documented upgrade path only; `localStorage` is the chosen client store).
- Changing `scoring.py`, `judge.py`, `rubric.py`, or the rubric manage/UI code.

## Decisions

### D1. Generation mode is drafter-only, not the full crew
A compare holds everything fixed (task, rubric, mode) and varies only the prompt. The prompt's `content` is a drafter instruction, so a single DRAFTER-model call (prompt as instruction + task as input + the existing `_templates_reference()` block) is a coherent, honest test of it.
- **Chosen**: one direct `LLM` call per draft via `src/llm.py::get_llm("DRAFTER")`; `src/crew.py` is untouched.
- **Alternative (rejected for now)**: run the full 4-agent crew per prompt with the prompt injected into the drafter's task. The auditor + revise stages *fix* drafter mistakes, masking the very differences a prompt compare tries to measure - it answers "which prompt survives audit best," not "which prompt drafts best." It is also ~4× the LLM cost per prompt. Captured as a follow-up, not this change.
- **Implication**: a compare does not exercise the production crew path. It is a prompt-quality instrument, not a system-fidelity test. Documented in the CLI/UI.

### D2. `prompt_type` is a free-string variant/lineage tag, not an enum
Prompts carry a lineage label (`baseline` / `experimental` / `improved` / `reverted` / `v2-strict` / …) so compare columns are legible and history reads clearly.
- **Chosen**: free-string `prompt_type` column on `prompts`, seeded `baseline` for the 19. Mirrors the prior change's deliberate decision to leave `purpose` free-string.
- **Alternative**: a constrained enum. Rejected - premature; the lineage vocabulary is user-driven and will churn. A free string serves both lineage (`experimental`) and content-style (`detailed`) tagging without schema changes.
- The compare view uses `prompt_type` as the column header (falling back to `prompt_name` when blank).

### D3. DB is source of truth; `localStorage` is a mirror + WIP, with a byte budget
The user asked to save data to both DB and `localStorage` "as much as possible." `localStorage` caps at ~5 MB (string-only, per-origin), so "as much as possible" is a real constraint, not a wish.
- **Chosen**:
  - **DB is source of truth** for all compare data (`compare_runs` + `eval_runs` incl. `draft_text`).
  - **`localStorage` mirror, two layers**: (1) WIP form state (selected prompts, task, rubric, mode, N) - tiny, always saved; (2) compact results matrix per compare (prompt_type headers, criterion titles, verdicts/pass-rates, judge reasoning) - saved under a byte-budget LRU cap (~4 MB, evict oldest compares first), with a versioned cache key (`lawcmp:v1`).
  - **`draft_text` is DB-only**, lazy-fetched on "view draft" - it is the bulkiest field and the matrix is clear without it.
  - **DB wins on conflict**: on load, paint from `localStorage` instantly, then reconcile with `GET /api/compare/{id}`; if the server row is newer/absent, DB overwrites (or the cache entry is dropped if the compare was deleted).
- **Alternative**: mirror everything including `draft_text`. Rejected - ~45 KB/compare of draft text would exhaust the 5 MB ceiling in ~100 compares and risk `QuotaExceededError` mid-write corrupting the current compare.
- **Upgrade path**: IndexedDB (~50 MB+) if drafts must be cached client-side later; documented, not built.

### D4. `compare_runs` grouping table + snapshotted columns on `eval_runs`, no FK
Mirrors the existing snapshot-no-FK pattern (`store_result` already snapshots rubric/task as text "so a run survives later edits or deletion"; design.md D7 of the prior change chose no FK between prompts and rubrics).
- **Chosen**:
  - New `compare_runs` table: `id`, `label`, `contract_type`, `rubric_name`, `task_desc`, `gen_mode`, `n_drafts`, `created_at`.
  - New `eval_runs` columns (all nullable, snapshotted): `compare_run_id` (the group), `prompt_name`, `prompt_type`, `variant_label`, `draft_text`.
  - No FK: rename/delete a prompt later → the historical compare still reads clearly from its snapshots. `compare_run_id` is a soft reference (integer), not a FK constraint, so deleting a compare can cascade by application logic without schema coupling.
- **Alternative**: a FK from `eval_runs.compare_run_id` → `compare_runs.id`. Rejected - inconsistent with the snapshot discipline the eval store already follows; FKs complicate the snapshot-on-edit guarantee.
- Standalone (non-compare) runs keep working: the new columns are null.

### D5. Guarded `ALTER TABLE` migration in `ensure_schema`
The prior change dodged migration by adding a *new* table (`CREATE TABLE IF NOT EXISTS`). Adding columns to *existing* `prompts` and `eval_runs` is the repo's first additive-column migration.
- **Chosen**: a small `_add_column_if_missing(conn, table, col, ddl)` helper (uses `PRAGMA table_info` to check, then `ALTER TABLE … ADD COLUMN`), called from `ensure_schema()` for each new column. Runs on every startup; idempotent and self-healing.
- **Alternative**: a one-off migration script. Rejected - fragments migration state; `ensure_schema` already runs on every `store_result`/`list_runs`, so folding migration there guarantees every environment converges.

### D6. Configurable N drafts per prompt; per-criterion pass-rate when N > 1
Generation is stochastic (DRAFTER temp 0.2); a single draft per prompt can flip verdicts by luck. The judge is temp 0.0 (stable), so noise is concentrated in generation.
- **Chosen**: `n_drafts` is a compare parameter (default 1). When N = 1, each matrix cell shows the binary verdict. When N > 1, each cell shows `k/N` pass-rate across the N drafts, and the run-level row shows mean pass-rate and all-pass count. `compare_runs.n_drafts` records N.
- **Implication**: N multiplies cost linearly. Default 1 keeps the common case cheap; users opt into N > 1 for statistical signal.
- The all-pass run score stays as-is (`evaluate_contract` unchanged); the matrix's per-criterion pass-rate is the discriminating surface, not the run score.

### D7. The matrix is the deliverable, not the run score
The rubric is all-pass: `score = 1.0` iff every criterion passes, else `0.0`. Across prompt variants this produces many `0.0` ties - the run score is non-discriminating.
- **Chosen**: the compare view leads with the **per-criterion matrix** (criteria × prompts, `prompt_type` headers), cell = verdict (N=1) or pass-rate (N>1), clickable for judge reasoning. Run-level `n_passed`/`n_criteria` and mean pass-rate are secondary headlines.
- **Implication**: the matrix + per-cell reasoning is where "see clearly" lives; the score is a tag, not the signal.

### D8. Reuse `evaluate_contract` unchanged; new `src/eval/compare.py` for orchestration
- **Chosen**: `compare.py` owns `run_compare(...)` (loop prompts × drafts → generate → `evaluate_contract` → `store_result` with compare tags → return grouped result), `store_compare(...)`/`list_compares()`/`get_compare()` persistence helpers (delegating to `store.py`), and a CLI mirroring `src/eval/run.py`. `scoring.py`/`judge.py` are untouched.
- **Alternative**: fold compare into `run.py`. Rejected - `run.py` is a single-contract evaluator; compare is a different shape (N prompts × N drafts). Separate module keeps both readable.

## Risks / Trade-offs

- **[Drafter-only is not the production path]** -> Stated non-goal; the compare is a prompt-quality instrument. Mitigation: the CLI/UI labels the mode; full-crew mode is a tracked follow-up, not a silent gap.
- **[`localStorage` quota exhaustion]** -> ~5 MB ceiling; mirroring drafts would exhaust it. Mitigation: D3 - byte-budget LRU (~4 MB), `draft_text` DB-only/lazy, versioned cache key. `QuotaExceededError` during a write triggers LRU eviction and retry, never a half-written current compare.
- **[Stale cache after schema/shape change]** -> A deploy changes the result shape; old `localStorage` serves stale data. Mitigation: versioned cache key (`lawcmp:v1`); bump on shape change → invalidate. Plus DB-wins reconciliation on load.
- **[Stochastic generation makes N=1 noisy]** -> Single-draft verdicts can flip on re-run. Mitigation: D6 - configurable N; default 1 for cost, N>1 for signal. Documented in the UI.
- **[Migration `ALTER` on every startup]** -> Adds a `PRAGMA table_info` check per startup. Negligible (a few ms, columns already exist after first run). Mitigation: the guard short-circuits when columns exist.
- **[Seeder overwrites `prompt_type` on re-run]** -> `seed_contract_prompts.py` sets `baseline`; re-running after a user re-tagged a seeded prompt resets it. Mitigation: same trade-off as the existing prompt seeder (documented); the seeder only touches the 19 seeded names, not user-authored variants.
- **[Compare cost scales with prompts × N]** -> A 3-prompt × N=3 compare = 9 drafts + 9 eval runs (each eval = K judge calls). Mitigation: N default 1; UI shows the draft/eval count before running; runs are async with progress.

## Migration Plan

- **Deploy**: additive only. On next startup, `ensure_schema()` runs the guarded `ALTER`s (adds `prompt_type` to `prompts`; adds `compare_run_id`/`prompt_name`/`prompt_type`/`variant_label`/`draft_text` to `eval_runs`; creates `compare_runs`). Existing `eval_runs`/`prompts` rows get null/`baseline` for new columns. Re-run `seed_contract_prompts.py` to set `prompt_type = 'baseline'` on the 19. No existing code path depends on the new columns, so standalone eval runs and the crew are unaffected.
- **Rollback**: drop the new `eval_runs` columns and the `compare_runs` table, remove `prompt_type` from `prompts` (or leave it null), and remove `src/eval/compare.py` + compare routes/UI. Existing eval/prompt/rubric behavior is unaffected because no existing code path depends on the additions.

## Open Questions

- **Generation mode confirmation** - drafter-only (D1) is the chosen default; confirm this is acceptable vs. wanting full-crew fidelity. Lean: drafter-only for the prompt-quality instrument; full-crew as a later mode.
- **Default N** - 1 (cheap) or 3 (signal)? Lean: ship default 1, let users raise it.
- **Async vs sync compare in the web UI** - a 3-prompt × N=3 compare can take minutes. Lean: async with a progress poll/SSE; the CLI is synchronous. Resolve during implementation.
- **Should standalone (non-compare) eval runs also tag `prompt_name`?** Lean: out of scope; compare-only for now. The columns are nullable so a later change can adopt them without migration.
