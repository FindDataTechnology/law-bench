## Context

`law-template` is a CrewAI Chinese contract-drafting system. Evaluation rubrics live in `db/evaluation_rules.db` (`rubrics` + `criteria`), created by `scripts/extract_harbor_rules.py` which owns the `SCHEMA` constant and `create_schema()` - the single source of truth every seeder calls. Harbor rubrics (`source LIKE 'harbor:%'`) are read-only and refreshed by re-running extraction; local rubrics (`source = local`) are fully managed via `src/eval/manage.py` and the FastAPI web app (`src/web/`: `routes/api.py` JSON, `routes/pages.py` HTML, `models.py` Pydantic, `templates/*.html`).

Generation prompts today are code: the crew's agent/task definitions live in `src/config/agents.yaml` + `tasks.yaml`, and per-type drafting guidance lives as `templates/*.md` files loaded into the drafter's context by `src/crew.py::_templates_reference()`. None of it is in the DB or manageable from the UI. Separately, the 19 per-class Chinese contract rubrics (one per 民法典 named type) were proposed by the now-removed `contract-class-rubrics-templates` change and never applied, so the DB still judges all contract types against one generic rubric (`contract_drafting_v1`).

`chinese_contracts_class.md` enumerates the 19 民法典 typical named contracts - the shared type vocabulary both the rubrics and the per-type drafting prompts are keyed on.

## Goals / Non-Goals

**Goals:**
- Add a `prompts` table to the shared schema for per-contract-type generation/drafting prompts, with idempotent seeding.
- Provide full CRUD for prompts in `src/eval/manage.py` mirroring the rubric manage layer.
- Provide a prompt management UI (HTML + JSON) in the existing web app, parallel to the rubric UI.
- (Re-)seed the 19 per-class Chinese contract rubrics into the DB via an idempotent script.
- Keep prompts and rubrics independent: separate tables, separate namespaces, separate manage/UI paths.

**Non-Goals:**
- Wiring the crew to read drafting prompts from the DB at runtime (follow-up change; `src/crew.py` and `src/config/*.yaml` are untouched).
- Re-including the 19 per-class seed template *files* under `templates/` (the removed change's template half). Generation guidance now lives in the `prompts` table, not files.
- Auto-selecting a rubric or prompt to match a drafted contract's type (intake clarifier unchanged).
- Any harbor-side prompt extraction (prompts are always `source = local`).

## Decisions

### D1. Add the `prompts` table to `extract_harbor_rules.py`'s `SCHEMA`
The schema has one source of truth (`SCHEMA` + `create_schema()`), already imported by both `seed_sample_local_rubric.py` and the harbor extractor. Adding the table there means every existing and new seeder picks it up with no extra wiring.
- **Chosen**: append `CREATE TABLE IF NOT EXISTS prompts (...)` to `SCHEMA`.
- **Alternative**: a standalone migration script. Rejected - fragments the schema and risks drift from the single-source-of-truth pattern the repo already follows.
- The harbor extractor's `create_schema()` will create the empty `prompts` table, but `upsert_harbor_rubric` only ever touches `rubrics`/`criteria`, so harbor behavior is unchanged.

### D2. `prompts` is a single flat table, not a parent-child pair
A prompt is one body of text keyed by contract type + purpose - it has no ordered sub-items like a rubric's criteria.
- **Chosen schema**: `id` PK, `name` (UNIQUE), `contract_type` (e.g. `sale`), `purpose` (e.g. `drafting`), `content` (the Chinese prompt body), `source` (`local`), `description`, `created_at`.
- **Alternative**: a `prompts` + `prompt_sections` parent-child mirroring `rubrics`/`criteria`. Rejected - over-normalized for a single text blob; the rubric/criteria split exists because criteria are independently ordered, named, and judged, which prompts are not.
- `name` is UNIQUE (not `(name, source)`) because prompts are always `source = local` - there is no harbor/local namespace collision to guard against.

### D3. Prompt provenance is always `local`; no harbor analog
Prompts are authored content, not extracted from an upstream package. There is no `HarborReadOnlyError` path and no "re-extract prompts" control.
- **Chosen**: `source` column retained for consistency with `rubrics`, always `local`. The manage layer enforces no read-only class.
- **Implication**: harbor re-extraction (which scopes its writes to `source LIKE 'harbor:%'` rows in `rubrics`) never touches the `prompts` table at all.

### D4. Mirror the rubric manage layer and web UI, do not generalize
`manage.py` and the web routes already encode a clean rubric-specific pattern (error classes, `_flash` redirects, form collection). Prompt CRUD parallels it rather than being abstracted into a generic resource framework.
- **Chosen**: add `list_prompts`/`get_prompt`/`create_prompt`/`update_prompt`/`delete_prompt` to `manage.py` reusing the existing `ManageError` subclasses (`NotFoundError`, `ConflictError`, `ValidationError`); add `/api/prompts` + `/prompts` HTML routes and `prompt_form.html`/`prompts_list.html`/`prompt_detail.html` templates mirroring the rubric ones; add a `Prompts` nav link to `base.html`.
- **Alternative**: a generic CRUD framework parameterized by table. Rejected - premature abstraction; the existing code values readability over DRY here, and two parallel sets are easier to read than one indirection.

### D5. Idempotent upsert by `name`, mirroring `upsert_local_rubric`
- **Chosen**: `upsert_local_prompt(conn, prompt, now_iso)` matches by `name` (UNIQUE), updates `contract_type`/`purpose`/`content`/`description` if present, else inserts. Unlike rubrics there are no child rows, so it is a single `UPDATE`/`INSERT` (no delete-then-reinsert).
- **Implication**: re-running `seed_contract_prompts.py` is safe and never duplicates. Editing a prompt through the UI then re-running the seeder will overwrite the edited content - documented in the seeder's docstring, same trade-off as `seed_sample_local_rubric.py`.

### D6. Re-include only the rubric half of the removed change
The removed `contract-class-rubrics-templates` change authored both 19 rubrics and 19 template files. This change re-includes the 19 rubrics (the "Chinese evaluate rules" the user asked for) and replaces the template half with DB-stored generation prompts.
- **Chosen**: `scripts/seed_contract_rubrics.py` holds the 19 rubric dicts (4 shared base criteria + 4-6 type-specific Chinese criteria each), idempotently upserted, harbor rows untouched.
- **Alternative**: also re-add the 19 `templates/*.md` files. Rejected - the user's "constructs generate prompts to the db" signals the generation guidance should live in the DB now, not as files; adding both would duplicate guidance.

### D7. Loose coupling between prompts and rubrics via shared `contract_type`
Prompts and rubrics for the same contract type share a `contract_type` label (e.g. `sale`) but have no foreign key.
- **Chosen**: no FK; a prompt's `contract_type` is a free label matching the rubric naming convention (`contract_<type>_v1`).
- **Alternative**: a `contract_types` reference table both point at. Rejected - premature; the 19-type vocabulary is stable and already encoded in `chinese_contracts_class.md`.

## Risks / Trade-offs

- **[Prompts stored but not yet consumed by the crew]** -> Stated non-goal; the management UI is the deliverable and a later change wires `src/crew.py` to load a prompt by `contract_type`. Mitigation: the `/api/prompts/{name}` JSON endpoint makes that wiring trivial.
- **[Seeder overwrites UI-edited prompts on re-run]** -> Same trade-off as the existing rubric seeder; documented in the seeder docstring. Mitigation: the seeder is opt-in (`uv run python scripts/seed_contract_prompts.py`), and `update_prompt` updates in place so manual edits persist until the next explicit seed.
- **[Schema edit to `extract_harbor_rules.py` could perturb harbor extraction]** -> The edit is purely additive (`CREATE TABLE IF NOT EXISTS`); `upsert_harbor_rubric` is unchanged. Mitigation: task 4.x re-runs harbor extraction and asserts row counts unchanged.
- **[Rubric criteria and prompt content overlap conceptually]** -> Distinct purposes: rubric criteria are PASS/FAIL evaluation checks (`guidance`); prompt `content` is drafting instruction. Different tables, different consumers (judge vs. future drafter). No duplication risk.
- **[Name collision between a prompt `name` and a rubric `name`]** -> Separate tables; no collision. The UI disambiguates via `/rubrics/{name}` vs `/prompts/{name}`.

## Migration Plan

- **Deploy**: additive only. The next run of any seeder (or `create_schema()`) creates the `prompts` table; existing `rubrics`/`criteria`/`eval_runs`/`eval_criteria_results` rows are untouched. Run `uv run python scripts/seed_contract_rubrics.py` then `uv run python scripts/seed_contract_prompts.py` to populate.
- **Rollback**: drop the `prompts` table and remove the two new seed scripts / prompt CRUD / prompt UI. Rubrics and the rest of the system are unaffected because no existing code path depends on `prompts`.

## Open Questions

- **`purpose` vocabulary**: free string vs. constrained enum (`drafting`/`clarify`/`audit`/`revise`). Lean: free string now, seeded with `drafting`; can constrain later without a schema change. Resolve during implementation.
- **Seed depth**: seed only the 19 per-type `drafting` prompts, or also seed the 4 shared role prompts (clarify/draft/audit/revise) from `tasks.yaml`? Lean: 19 per-type drafting prompts only (matches "constructs generate prompts"); shared role prompts stay in YAML until the crew-wiring follow-up.
