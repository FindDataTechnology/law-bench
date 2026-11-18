## 1. Dependencies & project setup

- [x] 1.1 Add `fastapi`, `uvicorn[standard]`, and `jinja2` to `pyproject.toml` `[project.dependencies]`
- [x] 1.2 Run `uv sync` and verify `uv run python -c "import fastapi, uvicorn, jinja2"` succeeds
- [x] 1.3 Create the `src/web/` package skeleton: `__init__.py`, `app.py`, `routes/`, `templates/`, `static/`

## 2. CRUD service (`src/eval/manage.py`)

- [x] 2.1 Create `src/eval/manage.py` with a `_connect()` helper reusing `rubric.DEFAULT_DB` and enabling `PRAGMA foreign_keys = ON`
- [x] 2.2 Add `_assert_local(rubric_id)` (raises on harbor rubrics) and a duplicate-local-name check helper that raise clear `ValueError`s
- [x] 2.3 Implement `create_rubric(name, context, description, criteria=[])` inserting a `source='local'` rubric and its criteria ordered by submission; reject duplicate local name
- [x] 2.4 Implement `update_rubric(rubric_id, name, context, description)` that rejects harbor rubrics and duplicate local names
- [x] 2.5 Implement `delete_rubric(rubric_id)` that rejects harbor rubrics (criteria cascade via FK)
- [x] 2.6 Implement `add_criterion`, `update_criterion`, `delete_criterion` that reject harbor rubrics and enforce unique criterion names within a rubric
- [x] 2.7 Implement `reorder_criteria(rubric_id, ordered_criterion_ids)` that rejects harbor rubrics and reassigns `ordinal`
- [x] 2.8 Add `list_rubrics_with_counts()` and `get_rubric_detail(name)` read helpers for the UI (extend `rubric.py` reads with criterion counts)

## 3. FastAPI app & JSON API (`src/web/`)

- [x] 3.1 Create `src/web/app.py` FastAPI app: mount `/static`, configure Jinja2 templates, include routers (local-only, no CORS)
- [x] 3.2 Define Pydantic request models for create/update rubric and criterion payloads
- [x] 3.3 Implement `GET /api/rubrics` (list with counts) and `GET /api/rubrics/{name}` (metadata + ordered criteria) returning JSON
- [x] 3.4 Implement `POST /api/rubrics` (create), `PATCH /api/rubrics/{name}` (update), `DELETE /api/rubrics/{name}` (delete)
- [x] 3.5 Implement criterion endpoints: `POST /api/rubrics/{name}/criteria`, `PATCH /api/rubrics/{name}/criteria/{cid}`, `DELETE .../{cid}`, `POST /api/rubrics/{name}/criteria/reorder`
- [x] 3.6 Implement `POST /api/harbor/extract` that runs `scripts/extract_harbor_rules.py` via subprocess and returns its summary + refreshed counts; surface non-zero exit as an error

## 4. HTML UI (Jinja2 templates)

- [x] 4.1 `rubrics_list.html`: table of rubrics (name, context, source, criterion count), links to detail, "New local rubric" and "Re-extract harbor" controls
- [x] 4.2 `rubric_detail.html`: rubric metadata + ordered criteria; edit/delete and add-criterion controls hidden or disabled when `source` starts with `harbor:`
- [x] 4.3 `rubric_form.html`: create/edit rubric metadata with an inline criteria editor (name/description/guidance per row; add/remove/move up/down)
- [x] 4.4 Add a base layout, minimal CSS, and vanilla JS for delete confirmations and criterion row reordering
- [x] 4.5 Wire HTML routes (`GET /`, `GET /rubrics/new`, `GET /rubrics/{name}`, and the `POST` form handlers) to `manage.py` and the templates

## 5. Run script & docs

- [x] 5.1 Add `scripts/serve_web.sh` running `uv run uvicorn src.web.app:app --reload --host 127.0.0.1 --port 8010` (port overridable via `RULES_WEB_PORT`)
- [x] 5.2 Add a short usage note (start command, port override, JSON endpoints) to a `src/web/README.md`

## 6. Validation & tests

- [x] 6.1 Add unit tests for `manage.py` against a temp SQLite DB: create/update/delete, duplicate-name rejection, harbor immutability, criterion uniqueness, reorder, cascade delete
- [x] 6.2 Smoke-test the live app against the existing `db/evaluation_rules.db`: list shows the 3 seeded rubrics; harbor rows reject edits/deletes; create/edit/delete a local rubric; harbor re-extract leaves local rows unchanged
- [x] 6.3 Run `openspec validate evaluation-rules-manager` and confirm `openspec status --change evaluation-rules-manager` reports all artifacts done
