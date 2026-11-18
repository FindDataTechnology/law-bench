## Context

This repo is a Chinese Contract Drafting multi-agent system (CrewAI + Volcengine Ark + deepeval). Evaluation rubrics and their criteria are stored in a SQLite database at `db/evaluation_rules.db` (tables `rubrics`, `criteria`), created by `scripts/extract_harbor_rules.py` and `scripts/seed_sample_local_rubric.py`. The existing `src/eval/` module reads them (`rubric.py`) and persists evaluation runs (`store.py`); a CLI (`python -m src.eval.run`) lists rubrics/runs.

Today there is no interactive way to browse or edit rules: viewing is CLI-only and authoring a local rubric requires writing a Python script. This change adds a small local web app on top of the existing storage. Constraints:

- **No schema changes** - the existing `rubrics`/`criteria` schema already supports local rubrics (`source = 'local'`) and harbor rubrics (`source LIKE 'harbor:%'`).
- **Preserve the harbor-extraction invariant** from the `evaluation-rules` spec: harbor re-extraction is idempotent and never touches local rows; local rows are user-authored.
- **Minimal new dependencies**, installed via `uv` (the project's existing package manager).
- **Local dev tool**: single process, binds to loopback, no auth.

## Goals / Non-Goals

**Goals:**
- Browse all rubrics and drill into a rubric's criteria, description, and provenance in a browser.
- Full CRUD on locally-authored rubrics and their criteria (create, edit metadata, add/edit/delete/reorder criteria, delete rubric).
- Harbor reference rubrics shown read-only; a one-click control re-runs harbor extraction to refresh them.
- A JSON API exposing the same data for scripting.
- One `uv run` command to start the app.

**Non-Goals:**
- Authentication, multi-user, or remote deployment (local-only).
- Editing harbor rubrics in place (refresh via extraction instead).
- Changes to the contract-drafting crew, the eval judge (`scoring.py`/`judge.py`), or the `eval_runs` results tables.
- A JavaScript SPA / separate frontend build.
- Viewing `eval_runs` history in the UI (possible future enhancement).

## Decisions

### 1. FastAPI + Jinja2 (server-rendered) with a JSON API, not an SPA
**Choice**: One FastAPI app renders HTML pages via Jinja2 templates and also returns JSON from the same routes (content negotiation / dedicated `/api` routes).
**Rationale**: FastAPI gives HTML and JSON from a single app, ships auto-docs, and is async-capable; Jinja2 keeps it server-rendered so there is no Node/JS build step - consistent with the project's Python-only toolchain. The management UI is CRUD over a few tables, so a SPA would be overkill.
**Alternatives**: (a) Flask + Jinja2 - simpler but no native async/OpenAPI; FastAPI is the modern default and pairs well with the existing async-friendly stack. (b) FastAPI + React SPA - richer UX but adds a frontend toolchain and a second process; not justified for this scope.

### 2. CRUD service in `src/eval/manage.py`, routes stay thin
**Choice**: A new `src/eval/manage.py` holds create/update/delete/reorder functions over `rubrics`/`criteria`; web routes call it. `src/eval/rubric.py` stays read-only.
**Rationale**: `rubric.py`'s documented purpose is *loading* rubrics, and `store.py` persists *runs* - putting writes in either muddies its role. A dedicated `manage.py` is reusable, unit-testable, and keeps HTTP handlers thin. The service enforces the harbor-immutability rule in one place.
**Alternatives**: (a) Extend `rubric.py` with writes - changes its read-only contract. (b) Inline SQL in routes - scatters persistence and is hard to test.

### 3. No schema migration; reuse existing tables
**Choice**: CRUD operates directly on the existing `rubrics`/`criteria` tables.
**Rationale**: The schema already supports everything needed (`source` distinguishes local vs harbor; `UNIQUE(rubric_id, name)` enforces criterion uniqueness; `ON DELETE CASCADE` drops criteria when a rubric is deleted).
**Alternatives**: New tables or a `managed_by` column - unnecessary and would require migrating the existing extraction/eval code.

### 4. Harbor immutability enforced at the service layer
**Choice**: Every write function in `manage.py` rejects rows whose `source LIKE 'harbor:%'`; the UI hides/disables edit controls for harbor rubrics and offers "Re-extract harbor rubrics" instead.
**Rationale**: Preserves the idempotent-extraction invariant and the read-only nature of reference data; defense-in-depth (UI + service) prevents accidental writes.
**Alternatives**: Allow editing harbor rows - would be clobbered on next extraction and breaks provenance.

### 5. Re-extraction delegates to the existing script
**Choice**: The "refresh harbor rubrics" control invokes `scripts/extract_harbor_rules.py` (subprocess) and shows its summary output.
**Rationale**: Reuses the idempotent extraction already specified and tested; no duplicated TOML-parsing logic.
**Alternatives**: Re-implement extraction in-process - duplicates logic and risks divergence.

### 6. Localhost-only bind, no auth
**Choice**: The app binds to `127.0.0.1:8010` and requires no login.
**Rationale**: This is a developer tool for managing a local SQLite file; auth would add friction with no threat model. Binding to loopback prevents exposure to the network.
**Alternatives**: Token auth - rejected as out of scope for a local tool.

### 7. Dependencies: `fastapi`, `uvicorn[standard]`, `jinja2`
**Choice**: Add these three to `pyproject.toml`; run with `uv run uvicorn src.web.app:app`.
**Rationale**: Minimal, all pure-Python-friendly, installed by the existing `uv sync` flow. `uvicorn[standard]` gives hot-reload (`--reload`) for development.
**Alternatives**: `flask` + `werkzeug` - see decision 1.

## Risks / Trade-offs

- **Concurrent SQLite writes (web + a manual extraction script run at the same time)** -> SQLite file locking serializes writers; extraction is infrequent and manual. Mitigation: document that extraction and editing should not run simultaneously; surface DB-locked errors clearly in the UI.
- **Deleting a rubric that past `eval_runs` reference** -> `eval_runs.rubric_name` is a text snapshot (not a foreign key), so deleting a rubric does not orphan runs - they remain valid historical snapshots. Trade-off: a deleted rubric's name persists in old runs. Mitigation: confirm-before-delete in the UI.
- **Editing a local rubric changes what future evaluations judge against** -> expected behavior (that's the point of managing rules). Mitigation: the UI always shows `source`/provenance so the user knows what they are editing.
- **No auth / writes enabled** -> acceptable for loopback-only. Mitigation: bind `127.0.0.1` only; do not enable `--host 0.0.0.0` by default.
- **Server-rendered UX is less dynamic** -> acceptable for a CRUD admin tool; small amount of vanilla JS for forms and delete confirmations. Trade-off: no rich client-side validation beyond HTML attributes.

## Migration Plan

1. Add `fastapi`, `uvicorn[standard]`, `jinja2` to `pyproject.toml` dependencies; run `uv sync`.
2. Add `src/eval/manage.py` (CRUD service).
3. Add `src/web/` (app factory, routes, templates, static assets) and `scripts/serve_web.sh`.
4. Run against the existing `db/evaluation_rules.db` - no migration step.
5. **Rollback**: remove `src/web/` and `src/eval/manage.py`, revert `pyproject.toml`; the database is untouched (any CRUD edits remain as ordinary data).

## Open Questions

- **Port**: defaulting to `8010` to avoid clashing with common dev ports (8000/3000). Overridable via env `RULES_WEB_PORT`.
- **Eval-runs view in v1?** Currently out of scope; can be added later as a read-only "Runs" page if desired.
