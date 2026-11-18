# Tasks — Add Selectable Contract-Generation Modes

## 1. Job table & CRUD (`src/eval/store.py`)

- [ ] 1.1 Add `generation_jobs` DDL to `ensure_schema()`: columns
  `id, kind, contract_type, status, result_ref (text), error_message,
  created_at, updated_at`. `kind ∈ {'batch','pipeline','auto_reject','regenerate'}`,
  `status ∈ {'pending','running','completed','failed'}`.
- [ ] 1.2 `store_generation_job(kind, contract_type) -> job_id` insert pending row.
- [ ] 1.3 `update_generation_job(job_id, *, status, result_ref=None,
  error_message=None)`.
- [ ] 1.4 `get_generation_job(job_id) -> dict | None`.
- [ ] 1.5 `list_generation_jobs(limit=20) -> list[dict]` (recent first).

## 2. Pydantic models (`src/web/models.py`)

- [ ] 2.1 `GenerationRequest` — `mode`, `stance`, `scenario`,
  `custom_clause_ids`, `format` (mirror `GenerateRequest` + `mode`).
- [ ] 2.2 `GenerationJobSubmit` response — `job_id`, `status`.
- [ ] 2.3 `GenerationJobDetail` response — full row incl. `result_ref` parsed.

## 3. New router (`src/web/routes/generation.py`)

- [ ] 3.1 `POST /api/contracts/{type}/generate-batch` — mode D, **sync**: wrap
  `contract_generate_batch` logic (or call `src.clauses.assemble` directly per
  combo), return `{results, success_count, failure_count}` + file URLs.
- [ ] 3.2 `POST /api/contracts/{type}/pipeline` — mode E, **async**: insert job
  row, `BackgroundTasks.add_task(_run_self_heal, job_id, ...)`, return 202 +
  `{job_id, status:'pending'}`. Background fn calls
  `run_self_heal_pipeline`, then `update_generation_job(..., status, result_ref=
  {"pipeline_run_id": id})`.
- [ ] 3.3 `POST /api/contracts/{type}/auto-reject` — mode F, async, calls
  `run_auto_reject_pipeline`, same job pattern; `result_ref` adds
  `learn_applied`.
- [ ] 3.4 `POST /api/contracts/{type}/regenerate-template` — mode G, async:
  `subprocess.run([sys.executable, GENERATE_TEMPLATES_SCRIPT, type, ...])`,
  capture stdout/stderr → `result_ref`/`error_message`.
- [ ] 3.5 `GET /api/generation-jobs` — list recent jobs.
- [ ] 3.6 `GET /api/generation-jobs/{id}` — single job detail (404 if missing).

## 4. App wiring (`src/web/app.py`)

- [ ] 4.1 `from .routes import generation; app.include_router(generation.router)`.
- [ ] 4.2 Confirm `ensure_schema()` creates `generation_jobs` on startup (it
  will, once 1.1 is in).

## 5. UI panel (`src/web/templates/contract_detail.html` + static JS)

- [ ] 5.1 Add the 「生成合同模板」 panel markup: mode radio group (A–G, A
  linking to the existing download buttons, B/C to existing `/generate` routes,
  D–G to the new routes), shared `stance` / `scenario` / `format` /
  `custom_clause_ids` inputs, 「生成」 button, result area.
- [ ] 5.2 `src/web/static/generation-panel.js`: serialize form, POST to the
  route matching the selected mode, render sync results (download links) or poll
  `/api/generation-jobs/{id}` every 3s for async, stop on terminal status,
  surface `failed` `error_message`.
- [ ] 5.3 Confirm dialog before triggering write modes (E/F/G) — name what each
  mutates (clauses DB / pipeline_runs / global `contracts.json`).

## 6. Tests

- [ ] 6.1 Job CRUD round-trip (store → update → get → list).
- [ ] 6.2 `POST .../generate-batch` returns results for a small type.
- [ ] 6.3 Async pipeline route returns 202 + job_id; polling reaches
  `completed`/`failed` (use a stub pipeline fn in tests).
- [ ] 6.4 Unknown contract type → 404; bad mode → 400.

## 7. Verification

- [ ] 7.1 `uv run pytest` green.
- [ ] 7.2 Manual: open `/contracts/sale`, run each mode from the panel, observe
  download link (sync) or job card → completed (async).
