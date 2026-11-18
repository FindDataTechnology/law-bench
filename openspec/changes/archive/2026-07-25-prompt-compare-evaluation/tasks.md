## 1. Schema: `prompt_type` on `prompts` + migration helper

- [x] 1.1 Add `prompt_type TEXT` column to the `prompts` `CREATE TABLE` in `SCHEMA` (`scripts/extract_harbor_rules.py`) for fresh DBs
- [x] 1.2 Add a guarded `_add_column_if_missing(conn, table, col, ddl)` helper (check `PRAGMA table_info`, then `ALTER TABLE … ADD COLUMN`) in `src/eval/store.py` or a shared `src/eval/db.py` helper
- [x] 1.3 Call the helper from `ensure_schema()` to add `prompt_type` to `prompts` on existing DBs; verify a fresh DB and an existing DB both end with the column (null on existing rows)

## 2. Schema: `compare_runs` table + `eval_runs` columns + migration

- [x] 2.1 Append `CREATE TABLE IF NOT EXISTS compare_runs (id, label, contract_type, rubric_name, task_desc, gen_mode, n_drafts, created_at)` to `RESULTS_SCHEMA` in `src/eval/store.py`
- [x] 2.2 Extend the `eval_runs` `CREATE TABLE` with nullable `compare_run_id INTEGER`, `prompt_name TEXT`, `prompt_type TEXT`, `variant_label TEXT`, `draft_text TEXT` (for fresh DBs)
- [x] 2.3 Add guarded `ALTER`s in `ensure_schema()` for the five new `eval_runs` columns on existing DBs; confirm no FK constraint is introduced
- [x] 2.4 Verify `store_result` still stores standalone runs (new columns null) and `list_runs` output is unchanged

## 3. Prompt CRUD: carry `prompt_type`

- [x] 3.1 Update `_require_prompt_fields`/`_prompt_detail`/`_get_prompt*` in `src/eval/prompt_crud.py` to read/write `prompt_type` (optional, no non-empty validation)
- [x] 3.2 Update `create_prompt`/`update_prompt` signatures to accept `prompt_type`; mirror in the `manage.py` re-export surface
- [x] 3.3 Confirm `list_prompts` includes `prompt_type` in the listing rows

## 4. Prompt seed: tag `baseline`

- [x] 4.1 Update `scripts/seed_contract_prompts.py` `_p(...)` and `upsert_local_prompt` to set `prompt_type = 'baseline'` on the 19 seeded prompts
- [x] 4.2 Re-run the seeder; verify the 19 prompts have `prompt_type = baseline` and existing rubric/criteria counts are unchanged

## 5. Prompt web API + models: carry `prompt_type`

- [x] 5.1 Add `prompt_type: Optional[str] = None` to `PromptCreate` and `PromptUpdate` in `src/web/models.py`
- [x] 5.2 Thread `prompt_type` through `POST /api/prompts` and `PATCH /api/prompts/{name}` in `src/web/routes/api.py`; confirm `GET` returns it

## 6. Prompt web UI: surface `prompt_type`

- [x] 6.1 Add a `prompt_type` input to `templates/prompt_form.html` (create + edit); collect it in the POST handlers in `src/web/routes/pages.py`
- [x] 6.2 Show `prompt_type` in `templates/prompts_list.html` (column) and `templates/prompt_detail.html`
- [x] 6.3 Smoke-test: create a prompt with `prompt_type = experimental`, view/edit/delete it; confirm blank is allowed

## 7. Compare orchestration (`src/eval/compare.py`)

- [x] 7.1 Create `src/eval/compare.py` with `run_compare(contract_type, rubric_name, task_desc, prompts, mode='drafter-only', n_drafts=1, db_path=DEFAULT_DB)` that loops prompts × drafts
- [x] 7.2 Implement drafter-only generation: one `get_llm("DRAFTER")` call per draft using the prompt `content` as instruction, the task as input, plus `_templates_reference()` (factor the helper so it is shared with `src/crew.py` without modifying the crew)
- [x] 7.3 For each draft, call `evaluate_contract(contract_text, rubric_name, task_desc)` unchanged and collect the result
- [x] 7.4 Implement `store_compare(...)` in `src/eval/store.py`: insert one `compare_runs` row, then store each run via an extended `store_result` that writes `compare_run_id`/`prompt_name`/`prompt_type`/`variant_label`/`draft_text`
- [x] 7.5 Implement `list_compares(limit)` and `get_compare(compare_id)` (grouped: `compare_runs` row + its `eval_runs` + each run's `eval_criteria_results`; exclude `draft_text` from the default payload)
- [x] 7.6 Implement `get_run_draft(compare_id, run_id)` returning the `draft_text` for lazy fetch
- [x] 7.7 When `n_drafts > 1`, aggregate per-prompt-per-criterion to a `k/N` pass-rate in the returned grouped result
- [x] 7.8 Confirm `src/crew.py`, `scoring.py`, `judge.py`, `rubric.py` are unchanged

## 8. Compare CLI (`python -m src.eval.compare`)

- [x] 8.1 Add `src/eval/compare.py` `main()` with argparse: `--contract-type`, `--rubric`, `--task`, `--prompts` (comma-separated), `--mode drafter-only`, `--n`, `--list-compares`
- [x] 8.2 Print the per-criteria × prompts matrix (verdict for N=1, `k/N` for N>1), run-level `n_passed`, and `DB compare id` line
- [x] 8.3 Smoke-test: run a 2-prompt compare for `sale` and `--list-compares`

## 9. Compare web API (`src/web/routes/api.py`)

- [x] 9.1 Add `POST /api/compare` (create+run; decide sync vs async per Open Questions - lean async w/ job id + progress), `GET /api/compare` (list), `GET /api/compare/{id}` (full grouped, no `draft_text`), `GET /api/compare/{id}/run/{run_id}/draft` (lazy `draft_text`)
- [x] 9.2 Add Pydantic models (`CompareCreate`, compare list/detail response shapes) to `src/web/models.py`
- [x] 9.3 Delegate to `src/eval/compare.py`; map service errors via existing `app.py` handlers

## 10. Compare web UI (`src/web/routes/pages.py` + templates)

- [x] 10.1 Add HTML routes: `GET /compare` (list), `GET /compare/new` (build form), `GET /compare/{id}` (result); define `/compare/new` before `/{id}`
- [x] 10.2 Create `templates/compare_list.html`, `templates/compare_form.html`, `templates/compare_detail.html`
- [x] 10.3 Render the per-criteria × prompts matrix in `compare_detail.html`: header = `prompt_type` (fallback `name`); cell = verdict (N=1) or `k/N` (N>1); cell expandable to judge reasoning; per-column "view draft" lazy-loads `draft_text`
- [x] 10.4 Show run-level `n_passed`/`n_criteria` and mean pass-rate as secondary headlines
- [x] 10.5 Add a `Compare` nav link to `templates/base.html`

## 11. `localStorage` mirror (`src/web/static/app.js`)

- [x] 11.1 Persist WIP form state (selected prompts, task, rubric, mode, n_drafts) to `localStorage` on every change; restore on `/compare/new` load
- [x] 11.2 After a compare completes, mirror the compact matrix + judge reasoning (no `draft_text`) to `localStorage` keyed by compare id, under a versioned key prefix (`lawcmp:v1`)
- [x] 11.3 On `/compare/{id}` load, paint from `localStorage` instantly, then reconcile with `GET /api/compare/{id}` (DB wins; drop entry if deleted)
- [x] 11.4 Implement byte-budget LRU eviction (~4 MB): before writing, evict oldest compare entries until the write fits; never partially write the current compare; on `QuotaExceededError`, evict and retry
- [x] 11.5 Invalidate old-version cache entries on version bump

## 12. Tests

- [x] 12.1 Extend `tests/test_manage.py`: prompt CRUD carries `prompt_type` (create/read/update/blank)
- [x] 12.2 Add migration tests: an existing DB without the new columns is migrated idempotently on `ensure_schema`; standalone runs still store/`list_runs` correctly
- [x] 12.3 Add `tests/test_compare.py` (or extend an eval test): `run_compare` with a stubbed drafter + stubbed judge creates one `compare_runs` row owning N `eval_runs` with snapshotted `prompt_name`/`prompt_type`/`draft_text`; `get_compare` returns the grouped result; `get_compare` survives prompt deletion
- [x] 12.4 Add web-route tests: `POST /api/compare`, `GET /api/compare`, `GET /api/compare/{id}` (no `draft_text`), `GET /api/compare/{id}/run/{rid}/draft`
- [x] 12.5 Run `uv run pytest` and confirm all green

## 13. Validation

- [x] 13.1 Run `openspec validate prompt-compare-evaluation` and `openspec status --change prompt-compare-evaluation`; confirm all artifacts done
- [x] 13.2 Re-run `seed_contract_prompts.py`; confirm 19 prompts tagged `baseline`, rubric/criteria counts unchanged, idempotent on re-run
- [x] 13.3 End-to-end: create `draft_sale` (baseline) + a `draft_sale_v2` (experimental) via the UI; run a compare for `sale` / `contract_sale_v1` / a fixed task with N=1 and N=2; verify the matrix renders, cells expand to reasoning, "view draft" lazy-loads, refresh preserves WIP, and the mirrored compare repaints from `localStorage`
