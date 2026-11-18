# Evaluation Rules Manager (web)

A local web app to browse and manage the evaluation rubrics and criteria stored
in `db/evaluation_rules.db` (the same SQLite file the contract-eval pipeline
uses). Built with FastAPI + Jinja2 — a single `uv run` process, no JavaScript
build step.

## Run it

```bash
bash scripts/serve_web.sh
# or pick a port:
RULES_WEB_PORT=8088 bash scripts/serve_web.sh
```

Then open <http://127.0.0.1:8010>. It binds to `127.0.0.1` only (local dev tool,
no auth).

## What you can do

- **Browse** all rubrics (harbor + local) and drill into a rubric's criteria.
- **Manage local rubrics**: create, edit metadata, delete; add / edit / reorder
  / delete criteria.
- **Harbor rubrics are read-only** (shown with a purple badge). Refresh them with
  the “Re-extract harbor” button, which re-runs `scripts/extract_harbor_rules.py`
  and leaves local rubrics untouched. Harbor must be installed
  (`uv tool install harbor`) for that button to succeed.

## JSON API

Everything the UI does is also exposed as JSON under `/api` (interactive docs at
[`/api/docs`](http://127.0.0.1:8010/api/docs)):

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/rubrics` | list rubrics with criterion counts |
| GET | `/api/rubrics/{name}` | a rubric + its ordered criteria |
| POST | `/api/rubrics` | create a local rubric (with optional criteria) |
| PATCH | `/api/rubrics/{name}` | update a local rubric's metadata |
| DELETE | `/api/rubrics/{name}` | delete a local rubric (cascades to criteria) |
| POST | `/api/rubrics/{name}/criteria` | add a criterion |
| PATCH | `/api/rubrics/{name}/criteria/{cid}` | update a criterion |
| DELETE | `/api/rubrics/{name}/criteria/{cid}` | delete a criterion |
| POST | `/api/rubrics/{name}/criteria/reorder` | reorder criteria by id list |
| POST | `/api/harbor/extract` | re-run harbor extraction |

Errors return a JSON `{"error": "..."}` with status `400` (validation),
`403` (harbor read-only), `404` (not found), or `409` (duplicate name).

## Contract context API (for agents)

A second JSON surface under `/api/contracts` exposes everything an external
agent needs to draft a Chinese contract over plain HTTP - the template
skeleton, per-slot instructions, the 法律法规 that apply, the tag dimensions
that specialize a contract, the clause catalog, and an assemble-and-render
endpoint. All of it is documented at `/api/docs` alongside the eval API.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/contracts` | list the 43 contract classes `[{key, zh}]` |
| GET | `/api/contracts/{type}` | comprehensive bundle: template + slots + laws + tags + sections + clause counts + rubric/prompt pointers |
| GET | `/api/contracts/{type}/slots` | slot-instruction manifest (with slot-ontology coverage); each entry carries `source` |
| GET | `/api/contracts/{type}/laws` | structured 法律法规 refs + full Doubao/DeepSeek survey markdown |
| GET | `/api/contracts/{type}/tags` | merged tag vocabulary `{dim: [values]}` for the type |
| GET | `/api/contracts/{type}/clauses` | clause catalog, filterable (`?scenario=&stance=&source=`) and paginated (`?limit=&offset=`) |
| POST | `/api/contracts/{type}/generate` | assemble + render; `format` defaults to `docx` (`pdf`/`both`/`markdown`) |

**Example agent flow** - discover, gather context, then generate:

```bash
# 1. what can I draft?
curl -s http://127.0.0.1:8010/api/contracts | jq '.[] | select(.key=="sale")'

# 2. everything sale needs in one call (template, slots, laws, tags, ...)
curl -s http://127.0.0.1:8010/api/contracts/sale | jq '{slots: .slot_instructions, tags: .tags, rubric: .rubric}'

# 3. assemble a sale contract for a scenario (default: docx)
curl -s -X POST http://127.0.0.1:8010/api/contracts/sale/generate \
  -H 'content-type: application/json' \
  -d '{"scenario":"生鲜乳购销","format":"markdown"}' | jq -r .body_text
```

`generate` returns `body_text` always; `docx`/`pdf`/`both` also return a
`docx_url`/`pdf_url` you can `GET` to download the file. A coherence-gate
failure (e.g. a clause selection that drops a canonical section) returns
`422` with a diagnostic; an unknown contract type returns `404`.

### Stored artifacts (MinIO + DB)

`generate` writes ephemeral local files. For persistence, use
`generate-stored` - it uploads the docx/pdf to MinIO and records a
`contract_artifacts` row, so a contract can be re-downloaded later **without
regenerating**. Identical inputs (same type + scenario + stance +
custom_clause_ids) are content-addressed by `md5(body_text)`: they reuse the
same `artifact_id` (`reused: true`); missing formats are filled in.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/contracts/{type}/generate-stored` | **by tag** (`scenario`/`stance`/`custom_clause_ids`): one variant -> `{artifact_id, docx_url, pdf_url, body_text, reused}`. **by type** (no tags): all `scenario × stance × base` combos -> `{artifacts: [...], count, new, reused, failed}`. `format` defaults to `docx` |
| GET | `/api/contracts/artifacts` | list stored artifacts (filter `?contract_type=`), newest first |
| GET | `/api/contracts/artifacts/{id}` | artifact metadata (incl. `body_text`) |
| GET | `/api/contracts/artifacts/{id}/download?format=docx` | stream the file from MinIO |

```bash
# by type: generate ALL tag combinations for sale (base + every scenario + every stance + crosses)
curl -s -X POST http://127.0.0.1:8010/api/contracts/sale/generate-stored \
  -H 'content-type: application/json' -d '{}' | jq '{count, new, reused, failed}'

# by tag: generate one specific variant (reuses the artifact if already stored)
curl -s -X POST http://127.0.0.1:8010/api/contracts/sale/generate-stored \
  -H 'content-type: application/json' \
  -d '{"scenario":"生鲜乳购销","format":"docx"}' | jq '{artifact_id, docx_url, reused}'

# download it directly later (no regeneration)
curl -s -OJ "http://127.0.0.1:8010/api/contracts/artifacts/1/download?format=docx"
```

The same surface is available to MCP agents as `contract_generate_stored` and
`contract_download`.

## Layout

```
src/web/
  app.py            # FastAPI app factory, static mount, exception handlers
  models.py         # Pydantic request models
  routes/api.py     # JSON API under /api (+ shared harbor-extraction helper)
  routes/pages.py   # server-rendered HTML routes
  templates/        # Jinja2: base, rubrics_list, rubric_detail, rubric_form
  static/           # style.css, app.js
src/eval/manage.py  # CRUD service (harbor-immutability, uniqueness, cascade)
```
