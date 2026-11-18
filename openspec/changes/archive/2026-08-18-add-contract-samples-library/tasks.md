# Tasks: Contract Samples Library

## 1. Service layer — `src/contracts/artifacts.py`

- [x] 1.1 Add `distinct_scenarios(contract_type, db=None) -> list[str]` — distinct non-null `scenario` values filtered by type, ordered. Reuse the module's existing `connect(db)` connection helper.
- [x] 1.2 Add `distinct_stances(contract_type, db=None) -> list[str]` — same shape, `stance`.
- [x] 1.3 Add `list_samples(contract_type=None, scenario=None, stance=None, limit=50, offset=0, db=None) -> tuple[list[dict], int]` — dynamic WHERE from non-None params; metadata-only projection (no `body_text`, reuses `_LIST_COLS`); separate `COUNT(*) AS total` for total; `ORDER BY id DESC`.
- [x] 1.4 Verify the three functions mirror the existing module's DB-access pattern (parameterized queries, no string interpolation of user input → no SQL injection surface).

## 2. Route — `src/web/routes/samples.py` (new)

- [x] 2.1 Create `router = APIRouter(tags=["samples"])`.
- [x] 2.2 Add `GET /samples` (`include_in_schema=False`, `name="page_samples"`) with query params `contract_type`, `scenario`, `stance`, `limit` (1–100, default 50), `offset` (≥0).
- [x] 2.3 Verify `list_contract_types` helper signature in `src/contracts/templates.py` (file-backed, returns `[{key, zh}]`) and import it correctly.
- [x] 2.4 Call `distinct_scenarios`/`distinct_stances` only when `contract_type` is set; build template context with `all_types`, `artifacts`, `total`, pagination booleans, selected values, option lists.
- [x] 2.5 Render via `_templates.TemplateResponse(request, "samples.html", ctx)`.

## 3. Template — `src/web/templates/samples.html` (new)

- [x] 3.1 `{% extends "base.html" %}` with title "合同样本库".
- [x] 3.2 Filter `<form method="GET">` with three `<select>`s (type/scenario/stance), `onchange="this.form.submit()"` + `<noscript>` submit button.
- [x] 3.3 Data `<table>` rendering `#`, `contract_type`, scenario (— for null), stance (— for null), slot count, download links.
- [x] 3.4 Download route is unnamed (auto-named by Starlette) → used literal path strings `/api/contracts/artifacts/{{ a.id }}/download?format=docx|pdf` (the documented fallback).
- [x] 3.5 Pagination block: prev/next `<a>` carrying all filter params; page-info span with current/total page count; disabled spans at bounds.

## 4. Wiring

- [x] 4.1 `src/web/app.py`: `from .routes import (..., samples, ...)` + `app.include_router(samples.router)`.
- [x] 4.2 `src/web/templates/base.html`: add "合同样本" nav link → `{{ url_for('page_samples') }}`.
- [x] 4.3 `src/web/static/style.css`: add `.filter-form`, `.filter-group`, `.data-table td.dl-cell`, `.pagination`, `.page-info` rules (additive, match existing conventions).

## 5. Tests — `tests/test_samples_page.py` (new)

- [x] 5.1 Service: `distinct_scenarios('sale')` returns the expected non-null set; `distinct_stances('sale')` likewise.
- [x] 5.2 Service: `list_samples(contract_type='sale')` returns `(rows, total)` with `total` matching `contract_artifacts` count for sale; rows exclude `body_text`.
- [x] 5.3 Service: `list_samples(contract_type='sale', scenario='农产品买卖')` excludes base (null-scenario) rows; `list_samples(contract_type='sale')` (no scenario) includes them.
- [x] 5.4 Service: pagination boundary — `offset=0, limit=50` first page; `offset` past total → empty rows, `total` unchanged; last page has `has_next=False`.
- [x] 5.5 Route: `GET /samples` → 200 and contains a `<table>`; `GET /samples?contract_type=sale` → 200 and scenario/stance options rendered.
- [x] 5.6 Route: `GET /samples?contract_type=sale&scenario=农产品买卖` narrows rows; `contract_type=nonexistent` → empty table, no 500.
- [x] 5.7 Run full suite: `uv run pytest -q` — 534 passed, 16 pre-existing failures (all generator-rules 43→66 debt, confirmed unrelated by stash-and-rerun), 57 skipped. No regressions from this change.

## 6. Verification (manual smoke)

- [ ] 6.1 `uv run uvicorn src.web.app:app --reload`, open `http://localhost:8010/samples` (or configured port).
- [ ] 6.2 Pick `sale` → confirm scenario dropdown populates with the distinct sale scenarios; pick one → table narrows.
- [ ] 6.3 Click DOCX on a row → file downloads; click PDF → file downloads.
- [ ] 6.4 Walk pagination: last page, first page, filter retained across pages.
