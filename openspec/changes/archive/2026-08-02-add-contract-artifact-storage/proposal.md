## Why

Contract generation already works end-to-end (`generate_contract_assembled` -> docx/pdf), and the `contract-context-api` change exposes it over HTTP + returns local file URLs. But every generation writes a fresh local file under `output/contracts/` with no record of what was produced - re-fetching means regenerating, files don't survive a pod restart, and there is no way to look up "the contract I generated for sale + 农产品买卖 last week". This change adds a persistence layer: generate by type or tags, **upload to MinIO**, record the artifact in **the DB** (keyed by content hash so identical inputs are never regenerated), and **download by artifact id** directly from MinIO - so a consumer can fetch a previously generated contract without regenerating it.

## What Changes

- **New storage service** (`src/contracts/artifacts.py` or `src/clauses/artifacts.py`): generate a contract (reusing `generate_contract_assembled`), upload the docx/pdf to **MinIO** (native `minio` SDK, new `MINIO_ARTIFACTS_PREFIX`), and record a row in a new `contract_artifacts` table. Content-addressed dedup: the assembled body is hashed; if an artifact with the same body hash already exists, its already-stored formats are reused and only missing formats are generated - identical inputs return the same artifact id (the "download without regenerating" goal).
- **New `contract_artifacts` DB table** (added to `src/eval/store.py` schema, created by `ensure_schema`): one row per distinct contract body - `id, contract_type, scenario, stance, custom_clause_ids, body_hash, body_text, slots, docx_key, pdf_key, minio_bucket, created_at, updated_at`, with a unique constraint on `body_hash`.
- **New HTTP endpoints** (added to the `contract_context` router, documented in `/api/docs`):
  - `POST /api/contracts/{type}/generate-stored` - generate + upload to MinIO + record in DB; returns `{artifact_id, docx_url, pdf_url, body_text, reused}`. `format` defaults to `docx` (matching the ephemeral `generate`); `both` stores both.
  - `GET /api/contracts/artifacts` - list stored artifacts (filterable by `?contract_type=`), newest first.
  - `GET /api/contracts/artifacts/{id}` - artifact metadata (no file bytes).
  - `GET /api/contracts/artifacts/{id}/download?format=docx` - stream the file from MinIO (server proxy, no client MinIO creds).
- **New MCP tools** (`fd-coding-law-bench-mcp/.../tools/artifacts.py`): `contract_generate_stored` (mirror of the HTTP endpoint) and `contract_download` (return artifact metadata + an HTTP download URL; MCP returns metadata, the agent fetches bytes over HTTP).
- **Settings**: add `MINIO_ARTIFACTS_PREFIX` (default `artifacts/`) to `src/settings.py`; reuse `MINIO_ENDPOINT`/`MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY`/`MINIO_SECURE`/`MINIO_BUCKET`.
- **No changes** to `generate_contract_assembled`, the coherence gate, the ephemeral `POST /generate` endpoint (kept as-is for quick local generation), or the assembly model.

## Capabilities

### New Capabilities
- `contract-artifact-storage`: persist generated contract docx/pdf to MinIO and a `contract_artifacts` DB table, content-addressed by body hash (identical inputs reuse the same artifact), and download by artifact id without regenerating. Exposed as HTTP endpoints under `/api/contracts/artifacts` + `POST /api/contracts/{type}/generate-stored`, and as MCP tools `contract_generate_stored` / `contract_download`.

### Modified Capabilities
<!-- None at the spec level. The new HTTP endpoints are added to the contract_context router (an implementation reuse of that route module), but no existing contract-context-api requirement changes. -->

## Impact

- **New code**: storage service module (MinIO upload + DB record + dedup); `contract_artifacts` table DDL in `src/eval/store.py`; new HTTP endpoints in `src/web/routes/contract_context.py` (or a small `contract_artifacts.py` router included alongside); new MCP tools file `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/tools/artifacts.py`.
- **New tests**: `tests/test_contract_artifact_storage.py` - generate-stored (docx/pdf/both), dedup (same inputs -> same id, missing format filled), list/get/download, unknown-type 404, missing-artifact 404; MCP tool tests in `fd-coding-law-bench-mcp/tests/`.
- **Modified code**: `src/settings.py` (add `MINIO_ARTIFACTS_PREFIX`); `src/eval/store.py` (add `contract_artifacts` DDL to `ensure_schema`); `src/web/routes/contract_context.py` (include the new endpoints, or a new router wired in `app.py`); MCP server tool registration.
- **Dependencies**: none new - the `minio` SDK (7.2.20) and `boto3` are already available; reuses `psycopg`, FastAPI.
- **Data**: new `contract_artifacts` table on the prod `law_bench` DB (auto-created on next `ensure_schema`); generated files stored in the existing MinIO bucket (`scraw-law-contracts`) under the `artifacts/` prefix. No migration of existing local files.
- **Operations**: the deployed `law-bench` pod must have MinIO env (`minio_host`, `minio_root_user`, `minio_root_password`, `MINIO_BUCKET`) - already present for the RAG search path; verify before deploy. The MinIO client must bypass the macOS/proxy `NO_PROXY=*` workaround already used by `src/search/minio_source.py`.
- **Out of scope**: presigned URLs (server proxy only in v1), versioning/history per artifact (dedup reuses the single row), deleting/expiring artifacts, and migrating the ephemeral local-file `generate` to use storage (it stays as a quick local path).
