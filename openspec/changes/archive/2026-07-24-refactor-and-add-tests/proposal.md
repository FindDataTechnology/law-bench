## Why

The project ships three subsystems — the CrewAI drafting pipeline (`src/crew.py`, `src/llm.py`, `main.py`), the evaluation engine (`src/eval/`), and a FastAPI web layer (`src/web/`) — but only two test files exist, both narrowly scoped: `tests/test_manage.py` covers the manage-layer CRUD, and `tests/test_web_prompts.py` covers the `/api/prompts` routes by mutating the **real** dev database. There is no coverage for the scoring/judge/store CLI engine, the rubric/criterion web routes, the HTML page flows, the app error handlers, or the drafting CLI. Meanwhile `src/eval/manage.py` has grown to 640 lines mixing rubric CRUD, criterion CRUD, and prompt CRUD with duplicated connection/validation helpers shared across modules — making it hard to test in isolation and hard to extend. We need a behavior-preserving refactor that lifts testability (injectable DB and judge, centralized config, smaller modules) and a full automated test suite that runs hermetically (no network, no dev-DB mutation) so the codebase has a regression contract before further feature work.

## What Changes

**Refactor (behavior-preserving, no public API changes):**
- Extract a single source of truth for paths/env in a new `src/settings.py` (DB path, repo root, templates dir, required env-var lists); `rubric.py`, `manage.py`, `store.py`, `crew.py`, `llm.py`, `judge.py`, and the web layer import from it instead of re-deriving paths.
- Split `src/eval/manage.py` into focused modules: `src/eval/db.py` (connection + row helpers, eliminating the duplicated `_connect` in `manage.py` and `store.py`), `src/eval/errors.py` (the `ManageError` hierarchy), `src/eval/rubric_crud.py`, and `src/eval/prompt_crud.py`. `manage.py` becomes a thin re-export facade so existing `from src.eval import manage as M` imports keep working.
- Make the web layer DB-injectable via a FastAPI `Depends(get_db)` dependency defaulting to `DEFAULT_DB`, overridable in tests through `app.dependency_overrides` so web tests no longer touch the dev DB.
- Replace `main.py`'s fragile `sys.argv[1:-1]` parsing with `argparse` (consistent with `src/eval/run.py`), preserving the `python main.py "<request>" [output.md]` interface.
- Tighten `src/llm.py` to raise a clear dedicated error (not a bare `KeyError`) when a role model env var is missing.

**Tests (full, hermetic):**
- Add a `tests/conftest.py` with shared fixtures: a seeded throwaway SQLite DB (real schema via `scripts/extract_harbor_rules.py`), a `TestClient` wired to it through the DB dependency override, and a deterministic fake LLM judge for scoring tests (no network).
- Add unit tests for every currently-uncovered module: `rubric.py`, `store.py`, `scoring.py` (with injected fake judge), `judge.py`, `llm.py`, `crew.py` (template loading; crew assembly without kickoff), and the new `db.py`/`errors.py`/config.
- Extend web coverage: `tests/test_web_api.py` for rubric + criterion routes (harbor read-only → 403, conflict → 409, validation → 400, not found → 404, reorder), and `tests/test_web_pages.py` for HTML form flows and flash redirects.
- Add `tests/test_app.py` for `create_app`, static/template mounts, and the `ManageError` → HTTP-status handler mapping.
- Add CLI tests for `main.py` and `src/eval/run.py` (`--list-rubrics`, missing-args errors, output-file writing) using `capsys`/`tmp_path` and monkeypatched services.
- Refactor the existing `tests/test_web_prompts.py` onto the hermetic DB fixture (no dev-DB mutation); keep `tests/test_manage.py` and extend it for the module split.

## Capabilities

### New Capabilities
- `test-suite`: An automated, hermetic test suite covering the drafting pipeline, evaluation engine, and web layer, runnable without external LLM/network access and without mutating the development database, establishing a behavioral regression contract.

### Modified Capabilities
<!-- Refactor is behavior-preserving: no existing spec-level requirement changes. -->

## Impact

- **Code**: `src/` restructured (new `src/settings.py`, `src/eval/db.py`, `src/eval/errors.py`, `src/eval/rubric_crud.py`, `src/eval/prompt_crud.py`; `manage.py` becomes a facade); `src/web/app.py`, `src/web/routes/api.py`, `src/web/routes/pages.py` gain a DB dependency; `main.py` rewritten to argparse; `src/llm.py` error path tightened. Public module surfaces (`manage.*`, route paths, CLI commands) are preserved.
- **Tests**: `tests/` grows from 2 files to ~12; new `conftest.py`; existing two test files updated.
- **Dependencies**: No new runtime dependencies (pytest already in the `dev` group); possibly add `pytest` test-path/config tweaks in `pyproject.toml`.
- **Specs**: Adds `specs/test-suite/spec.md`. No existing spec deltas (refactor preserves behavior).
- **Risk**: Module split and DB-dependency threading touch most of `src/`; mitigated by keeping `manage.py` as a re-export facade and by writing tests before/alongside each move.
