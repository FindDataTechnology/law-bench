## Why

The repo's contract-drafting crew reads its generation prompts from `src/config/*.yaml` and `templates/*.md` - authoring prompts means editing code, and there is no way to view or revise them through the existing web UI. Meanwhile the per-class **Chinese evaluate rules** (one rubric per 民法典 named contract type) only ever existed as a proposed-but-unapplied change that has since been removed, so the DB still judges every contract type against a single generic rubric. This change centralizes both bodies of content in `db/evaluation_rules.db` and makes them manageable from the web: it (re)seeds the 19 per-class Chinese rubrics and introduces a new `prompts` table for per-contract-type drafting prompts, with a management UI for the prompts.

## What Changes

- **New `prompts` table** in the shared schema (added to `scripts/extract_harbor_rules.py`'s `SCHEMA`, the single source of truth, so every seeding script picks it up via `create_schema()`). Columns: `name` (unique), `contract_type`, `purpose` (e.g. `drafting`), `content` (the Chinese prompt body), `source` (`local`), `description`, `created_at`. No harbor analog - prompts are always locally authored and fully editable.
- **New `scripts/seed_contract_prompts.py`**: a registry of per-contract-type drafting prompts (one per 民法典 type, mirroring the rubric set), idempotently upserted into `prompts`. Re-running never duplicates and never touches `rubrics`/`criteria`.
- **Re-include the 19 per-class Chinese rubrics** via `scripts/seed_contract_rubrics.py` (the rubric half of the removed `contract-class-rubrics-templates` change): each `contract_<type>_v1` rubric = the 4 shared base criteria + 4-6 type-specific Chinese criteria drawn from the type's 民法典 mandatory-clause set; `source = local`, `context = contract`; idempotent upsert, harbor rows untouched.
- **Prompt CRUD in `src/eval/manage.py`**: parallel to the rubric manage layer - `list_prompts`, `get_prompt`, `create_prompt`, `update_prompt`, `delete_prompt` - with the same error vocabulary (`NotFoundError`, `ConflictError`, `ValidationError`). No `HarborReadOnlyError` analog (prompts are never harbor-sourced).
- **Prompt management UI** in the web app: JSON endpoints under `/api/prompts` and HTML pages (`/prompts`, `/prompts/new`, `/prompts/{name}`, edit/delete) added to `src/web/routes/api.py` + `pages.py`, with Pydantic models in `src/web/models.py` and Jinja templates mirroring the rubric UI. A top-level nav link joins the two management areas.
- **No changes** to `scoring.py`, `judge.py`, `rubric.py`, `run.py`, the crew, or the rubric manage/UI code - all remain unchanged. Wiring the crew to read drafting prompts from the DB at runtime is explicitly out of scope (a follow-up); this change only stores and manages them.

## Capabilities

### New Capabilities
- `generation-prompts`: storage of per-contract-type generation/drafting prompts in a `prompts` table within `db/evaluation_rules.db`, with idempotent seeding and the same local/harbor provenance discipline as rubrics (prompts are always `source = local`).
- `generation-prompts-web`: a management UI (HTML + JSON API) in the existing FastAPI web app for creating, viewing, editing, and deleting generation prompts, paralleling the rubric management UI.

### Modified Capabilities
- `evaluation-rules`: add a requirement that the schema supports an idempotently-seeded set of per-class Chinese contract rubrics (one per 民法典 named type, `source = local`, `context = contract`), coexisting with harbor and existing local rubrics.

## Impact

- **New data**: 19 per-class rubrics (~130-150 criteria) + 19 per-type drafting prompts in `db/evaluation_rules.db`.
- **New code**: `scripts/seed_contract_rubrics.py`, `scripts/seed_contract_prompts.py`; prompt CRUD in `src/eval/manage.py`; prompt routes + models + templates in `src/web/`; a `prompts` nav link.
- **Modified code**: `scripts/extract_harbor_rules.py` `SCHEMA` (adds the `prompts` table - additive, no migration of existing rows); `src/web/app.py` (no change expected - routes auto-included).
- **Reused as-is**: the `rubrics`/`criteria` schema, `src/eval/*` rubric/judge/scoring/run modules, `src/crew.py`, the rubric manage layer and rubric web UI.
- **Dependencies**: none new (FastAPI, Pydantic, sqlite3 already in use).
- **Operations**: `uv run python scripts/seed_contract_rubrics.py` and `uv run python scripts/seed_contract_prompts.py` to seed; manage via the web UI (`uv run uvicorn src.web.app:app ...`) or `/api/prompts`.
- **Out of scope**: crew runtime consumption of DB prompts; per-class seed template *files* under `templates/` (the removed change's template half is not re-included - generation guidance now lives in the `prompts` table instead); template/rubric auto-selection by the intake clarifier.
