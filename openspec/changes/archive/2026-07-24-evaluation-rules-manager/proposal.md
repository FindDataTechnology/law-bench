## Why

Evaluation rubrics and their criteria live in `db/evaluation_rules.db`, but the only ways to see or change them today are CLI scripts (`scripts/extract_harbor_rules.py`, `scripts/seed_sample_local_rubric.py`, `python -m src.eval.run --list-rubrics`). There is no way to browse a rubric's criteria, source, or provenance at a glance, and no way to author or tune a local rubric without writing a Python script. A small local web app lets a user see and manage evaluation rules directly, lowering the friction to build and refine contract-evaluation rubrics.

## What Changes

- Add a local web app (FastAPI + Jinja2, a single `uv run` process) that shows and manages evaluation rules.
- **Browse**: list all rubrics with their source, context, and criterion count; drill into a rubric to see its description, provenance, and criteria (name, description, guidance, ordinal).
- **Manage local rubrics**: create, edit metadata, and delete locally-authored rubrics (`source = local`); add, edit, reorder, and delete their criteria.
- **Protect reference data**: harbor rubrics (`source LIKE 'harbor:%'`) are read-only in the UI; a control re-runs harbor extraction (the existing script) to refresh them.
- Expose a JSON API alongside the HTML UI so the same data is scriptable.
- Add a CRUD service (`src/eval/manage.py`) over the existing SQLite schema — no schema changes.
- New dependencies: `fastapi`, `uvicorn`, `jinja2` (added to `pyproject.toml`, installed via `uv sync`).

## Capabilities

### New Capabilities
- `evaluation-rules-web`: A local web UI and REST API to browse evaluation rubrics and criteria, perform CRUD on locally-authored rubrics, view harbor reference rubrics read-only, and trigger harbor re-extraction.

### Modified Capabilities
<!-- None. The existing `evaluation-rules` storage spec is unchanged; this change builds on top of it. -->

## Impact

- **New code**: `src/web/` (FastAPI app, routes, Jinja2 templates, static assets) and `src/eval/manage.py` (rubric/criteria CRUD service).
- **Reused as-is**: `src/eval/rubric.py` (read), `db/evaluation_rules.db` schema (no migration), the existing harbor extraction script (invoked for refresh).
- **Dependencies**: add `fastapi`, `uvicorn`, `jinja2` to `pyproject.toml`.
- **Operations**: runs locally via `uv run uvicorn ...`, binds to `127.0.0.1`; no auth (local dev tool).
- **Out of scope**: the contract-drafting crew, the eval judge pipeline, and the `eval_runs` results tables are not changed.
