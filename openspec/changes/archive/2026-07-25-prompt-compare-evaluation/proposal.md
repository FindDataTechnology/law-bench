## Why

The repo can already draft contracts (`src/crew.py`) and evaluate a drafted contract against a rubric (`src/eval/scoring.py::evaluate_contract`, persisted by `src/eval/store.py`). The `prompts` table holds per-contract-type drafting prompts, manageable from the web. But there is **no way to compare prompts against each other**: an `eval_runs` row records *which rubric* judged a draft and *which file* the draft lived in, never *which prompt produced it*, and nothing groups runs into a comparison. So when authoring or revising a drafting prompt, there is no grounded signal for "did this change make drafts better or worse" - only gut feel. This change adds an end-to-end **prompt compare**: for a fixed area (contract type + rubric + task), draft a contract with each selected prompt, run the real deepeval judge on each draft, persist the grouped results, and render a per-criterion matrix that makes the differences visible. Results are mirrored to browser `localStorage` so the view is instant and survives refresh.

## What Changes

- **`prompt_type` field on prompts** (variant/lineage tag, free string: `baseline` / `experimental` / `improved` / `reverted` / …). The 19 seeded prompts get `baseline`; user-authored variants carry their lineage label. Stored in the `prompts` table (schema source of truth: `scripts/extract_harbor_rules.py`'s `SCHEMA`), surfaced in the prompt CRUD UI, and used as the column header in the compare matrix.
- **New `compare_runs` table** in `db/evaluation_rules.db`: one row per compare (label, contract_type, rubric_name, task_desc, gen_mode, n_drafts, created_at) - the grouping that `eval_runs` currently lacks.
- **New columns on `eval_runs`** (snapshotted, no FK - mirrors the existing snapshot pattern): `compare_run_id`, `prompt_name`, `prompt_type`, `variant_label`, `draft_text`. A run now records which prompt produced the draft it scored, which compare it belongs to, and the draft text itself (so a compare survives `output/` cleanup). Standalone (non-compare) runs keep working with these columns null.
- **Guarded migration** in `src/eval/store.py::ensure_schema`: `ALTER TABLE … ADD COLUMN` guarded by a `PRAGMA table_info` check, run on every startup. This is the repo's first additive-column migration (the prior change dodged it by adding a new table); the guard makes it idempotent and self-healing.
- **New `src/eval/compare.py`** orchestration: given an area (contract_type, rubric, task), a set of prompts, a generation mode, and N drafts/prompt - for each prompt, generate a draft (drafter-only LLM call), call `evaluate_contract()` unchanged, and persist the runs grouped under one `compare_run`. Reuses the existing judge; no new eval logic.
- **Drafter-only generation mode**: a single LLM call per draft using the DRAFTER model, the prompt's `content` as instruction, the task as input, plus the existing `_templates_reference()` block. The full 4-agent crew is explicitly a follow-up (its audit+revise stages mask the drafter-level differences a prompt compare is trying to measure).
- **Compare CLI** (`python -m src.eval.compare ...`) paralleling `src/eval/run.py`, and a **compare web UI + JSON API** (`/compare`, `/api/compare`) paralleling the prompt/rubric UI pattern. The web view renders the per-criterion matrix (criteria × prompts, `prompt_type` as column headers), with run-level `n_passed` and pass-rate; clicking a cell reveals the judge reasoning; "view draft" lazy-loads `draft_text`.
- **`localStorage` mirror** (client, `src/web/static/app.js`): (1) WIP form state - selected prompts, task, rubric, mode, N - persisted across refresh; (2) the compact results matrix + judge reasoning mirrored per compare, under a byte-budget LRU cap (~4 MB), with a versioned cache key and DB-wins reconciliation on load. `draft_text` is DB-only and lazy-fetched (not mirrored), keeping the cache safely under the ~5 MB `localStorage` ceiling. IndexedDB is documented as the upgrade path if drafts must be cached client-side later.

## Capabilities

### New Capabilities
- `prompt-compare`: orchestrate a compare run - generate a draft per selected prompt (drafter-only), evaluate each against a rubric, persist runs grouped as a `compare_run`, and query/list compares. Reuses the existing `evaluate_contract` judge unchanged.
- `prompt-compare-web`: a web UI (HTML + JSON API) in the existing FastAPI app for building, running, and viewing compares, plus a `localStorage` mirror (WIP form state + compact results matrix) for instant, refresh-surviving review.

### Modified Capabilities
- `evaluation-rules`: add the `compare_runs` table and the compare-driven columns on `eval_runs` (`compare_run_id`, `prompt_name`, `prompt_type`, `variant_label`, `draft_text`), with an idempotent guarded migration in `ensure_schema`.
- `generation-prompts`: add a `prompt_type` field (free-string variant/lineage tag) to prompt storage, seeded `baseline` for the 19 per-type prompts.
- `generation-prompts-web`: surface `prompt_type` in the prompt form, list, and detail views.

## Impact

- **New code**: `src/eval/compare.py` (orchestration + CLI); compare routes in `src/web/routes/api.py` + `pages.py`; Pydantic models in `src/web/models.py`; `templates/compare_*.html`; `localStorage` mirror logic in `src/web/static/app.js`; a `Compare` nav link.
- **Modified code**: `scripts/extract_harbor_rules.py` `SCHEMA` (adds `prompt_type` to `prompts` - additive); `scripts/seed_contract_prompts.py` (sets `prompt_type = 'baseline'`); `src/eval/store.py` (new `compare_runs` table, new `eval_runs` columns, guarded `ALTER` migration, `store_compare`/`list_compares`/`get_compare` helpers); `src/eval/manage.py` prompt CRUD (read/write `prompt_type`); prompt web models/routes/templates (carry `prompt_type`).
- **Reused as-is**: `src/eval/scoring.py::evaluate_contract`, `src/eval/judge.py`, `src/eval/rubric.py`, `src/llm.py::get_llm`, the `rubrics`/`criteria` schema, the rubric manage/UI code. `src/crew.py` is **not** modified (drafter-only generation is a direct LLM call, not the crew).
- **Dependencies**: none new (FastAPI, Pydantic, sqlite3, CrewAI's `LLM`, browser `localStorage` already in use).
- **Operations**: `uv run python -m src.eval.compare --contract-type sale --rubric contract_sale_v1 --task "…" --prompts draft_sale,draft_sale_v2 --mode drafter-only --n 1`; or via the web UI at `/compare`.
- **Out of scope**: full-crew generation mode (follow-up - its audit+revise stages mask drafter differences); auto-mutating a base prompt into variants (users author variants by hand via existing prompt CRUD); wiring the production crew to consume `prompts` at runtime (still the separate prior follow-up); IndexedDB client storage (documented upgrade path only).
