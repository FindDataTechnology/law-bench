# Proposal: Contract Samples Library

## Why

All 66 contract types have been generated and uploaded to MinIO as 724 content-addressed artifacts (315 new + 241 reused; see [[contract-corpus-in-minio]]). Today these are reachable only via JSON API endpoints (`/api/contracts/artifacts` and `/api/contracts/artifacts/{id}/download`), which are developer-facing and require manual query construction. There is no human-facing way to browse the corpus, inspect what variants exist (scenario × stance combinations), and download DOCX/PDF samples directly.

A web page that surfaces the existing artifact store — with type/scenario/stance filtering and per-artifact download links — closes that gap with zero new generation logic: it is a thin read + render layer over infrastructure that already works.

## What Changes

- Add a server-rendered `/samples` HTML page (Jinja2, same pattern as existing pages in `src/web/routes/pages.py`) that lists `contract_artifacts` rows in a paginated table with a three-level filter form (contract type → scenario → stance).
- Add three read-only query helpers to `src/contracts/artifacts.py`: `list_samples()` (filtered + paginated, returns `(rows, total)`), `distinct_scenarios(contract_type)`, and `distinct_stances(contract_type)`. Existing `list_artifacts` / `download` are untouched (backward-compatible API).
- Scenario and stance dropdowns are **type-cascaded**: selecting a contract type triggers a server reload that populates the scenario/stance options from that type's actual artifact rows (`SELECT DISTINCT`). Without a type selected, only "全部" is offered.
- Reuse the existing `GET /api/contracts/artifacts/{id}/download?format=` endpoint as `<a href>` targets — no new download path, no JS required for downloads.
- Wire the router into `src/web/app.py` and add a "合同样本" link to the base nav.
- **Out of scope**: slot filling / generation (handled by the add-contract-generation-modes feature), live text search, bulk zip export, compare mode, download analytics.

## Capabilities

### New Capabilities

- `contract-samples`: a browse-and-download UI over the MinIO artifact corpus. Requirements — paginated artifact table (server-side `LIMIT/OFFSET`, default 50/page); three-level filter (contract type required-by-UX, scenario/stance optional, each in a binary "全部 \| specific value" state); type-cascaded scenario/stance option lists sourced from `SELECT DISTINCT` on `contract_artifacts`; direct DOCX/PDF download via reused streaming endpoint; zero JavaScript for core flow (progressive enhancement only for optional field-name expand/collapse).

### Modified Capabilities

- `contract-artifacts` (the existing MinIO storage + API capability): the service module `src/contracts/artifacts.py` gains three read-only query functions. The existing public functions (`generate_stored`, `list_artifacts`, `get_artifact`, `download`) and the `/api/contracts/artifacts/*` JSON routes are unchanged in signature and behavior; the additions are purely additive.

## Impact

- **New files**: `src/web/routes/samples.py` (page route), `src/web/templates/samples.html` (Jinja2 template), `tests/test_samples_page.py` (service + route tests).
- **Modified files**: `src/contracts/artifacts.py` (append 3 functions, no edits to existing), `src/web/app.py` (`include_router`), `src/web/templates/base.html` (nav link), `src/web/static/style.css` (filter form + table styling, additive).
- **Unchanged**: generation pipeline, slot system, clause library, eval/rubric layer, existing artifact API endpoints, MinIO client config.
- **Data**: no schema migration. `contract_artifacts` already stores `tags->>'scenario'` / `tags->>'stance'` / `contract_type` per row (set by `generate_stored`). New queries read these existing columns; no new columns or indexes required for 724 rows (a GIN index on `tags` can be added later if the corpus grows 100×).
- **Dependencies**: none added (FastAPI + Jinja2 + psycopg already in use).
- **Tests**: new test file exercises the 3 service functions (distinct sets, filtering, pagination boundaries) and the `/samples` route (200, filter params, empty-result handling). Existing suite unaffected — additive only.
