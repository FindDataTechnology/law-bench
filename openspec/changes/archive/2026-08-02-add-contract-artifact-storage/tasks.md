## 1. Settings + DB schema

- [x] 1.1 Add `MINIO_ARTIFACTS_PREFIX = _env("MINIO_ARTIFACTS_PREFIX", "artifacts/")` to `src/settings.py` (near the existing `MINIO_*` block) and include it in the env/redacted-exports lists
- [x] 1.2 Add the `contract_artifacts` table DDL to `src/eval/store.py` (columns per spec: id, contract_type, scenario, stance, custom_clause_ids jsonb, body_hash, body_text, slots jsonb, docx_key, pdf_key, minio_bucket, created_at, updated_at; `UNIQUE(body_hash)`); add it to the `ensure_schema()` multi-statement so it is created on first run

## 2. Storage service (`src/contracts/artifacts.py`)

- [x] 2.1 Create `src/contracts/artifacts.py`; set `os.environ.setdefault("NO_PROXY", "*")` (mirror `src/search/minio_source.py`); build a `Minio` client from `MINIO_ENDPOINT`/`MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY`/`MINIO_SECURE` (lazily, cached); ensure the `MINIO_BUCKET` exists (`make_bucket` if missing, ignore `BucketAlreadyOwnedByYou`)
- [x] 2.2 `generate_stored(contract_type, *, scenario=None, stance=None, custom_clause_ids=None, format="docx", db=None) -> dict`: call `generate_contract_assembled(...)` to get `body_text`+`docx_path`+`pdf_path`+`slots`; compute `body_hash = md5(body_text)`; `SELECT` by `body_hash`; reuse-or-insert per D3 (fill missing formats by uploading the corresponding `*_path` to MinIO, update row); return `{artifact_id, docx_url, pdf_url, body_text, slots, reused}` where URLs are `/api/contracts/artifacts/{id}/download?format=...`
- [x] 2.3 `_upload(contract_type, artifact_id, path, ext) -> key`: `fput_object` to `{MINIO_ARTIFACTS_PREFIX}{contract_type}/{artifact_id}.{ext}`, return the key; store `minio_bucket` on the row
- [x] 2.4 `get_artifact(artifact_id, db=None) -> dict | None`: full row incl. `body_text`; raise/return None for missing
- [x] 2.5 `list_artifacts(contract_type=None, db=None) -> list[dict]`: rows excluding `body_text`, newest first
- [x] 2.6 `download(artifact_id, format, db=None) -> tuple[bytes, content_type]`: fetch the object from MinIO via `get_object`, return (stream, content-type); raise `NotFoundError` if the id or the requested format key is missing

## 3. HTTP endpoints (in `src/web/routes/contract_context.py` or a new `contract_artifacts.py` router)

- [x] 3.1 `POST /api/contracts/{contract_type}/generate-stored` accepting `{scenario?, stance?, custom_clause_ids?, format}` (`format` default `"docx"`, `Literal["docx","pdf","both","markdown"]`); call `generate_stored`; map `CoherenceError`->422, `NotFoundError`->404 (propagate to app handler); return the dict
- [x] 3.2 `GET /api/contracts/artifacts` (optional `?contract_type=`) -> `list_artifacts` projected (no `body_text`)
- [x] 3.3 `GET /api/contracts/artifacts/{id}` -> `get_artifact` (full row incl. `body_text`); 404 on missing
- [x] 3.4 `GET /api/contracts/artifacts/{id}/download?format=docx|pdf` -> `StreamingResponse` from `download(...)` with the right `Content-Type` + `Content-Disposition: attachment; filename="{contract_type}.{ext}"`; 404 on missing id or missing format
- [x] 3.5 Verify all four new paths appear in `GET /openapi.json` (none use `include_in_schema=False`)

## 4. MCP tools (`fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/tools/artifacts.py`)

- [x] 4.1 `contract_generate_stored(contract_type, format="docx", tags=None, stance=None, custom_clause_ids=None) -> dict`: call `src.contracts.artifacts.generate_stored` (via the existing `_sync_call`/`anyio` pattern used by other tools); return `{artifact_id, docx_url, pdf_url, body_text, slots, reused}`; registered `@mcp.tool(tags={"contracts"})`
- [x] 4.2 `contract_download(artifact_id, format=None) -> dict`: call `get_artifact`; return metadata + `download_url`/`download_urls` pointing at the HTTP download endpoint
- [x] 4.3 Register both tools in the server (follow the existing `tools/__init__.py` import pattern); verify they appear in `mcp` tool list

## 5. Tests

- [x] 5.1 `tests/test_contract_artifact_storage.py` (service + HTTP, via `app_client`/`seeded_db`): seed one base clause; generate-stored docx (200, artifact_id, docx_url, reused false); generate-stored markdown (urls null); generate-stored both (both keys); dedup same inputs (same id, reused true, no re-upload); missing-format fill (docx then pdf -> same id, both keys); list (filter by type); get metadata (body_text present); download docx (200, content-type); download missing format (404); unknown type (404); unknown artifact (404)
- [x] 5.2 MinIO-backed tests: use the existing MinIO test fixture/pattern from `tests/` (or `moto`/mock if no MinIO in CI) - verify `fput_object` is called with the expected key and `get_object` streams the bytes
- [x] 5.3 `fd-coding-law-bench-mcp/tests/test_artifacts_tool.py`: `contract_generate_stored` returns the expected shape; `contract_download` returns metadata + URL
- [x] 5.4 Run `pytest tests/test_contract_artifact_storage.py tests/test_contract_context_api.py` green (no regression on the context API)

## 6. Docs + deploy

- [x] 6.1 Extend the "Contract context API" section in `src/web/README.md` with the generate-stored + artifacts endpoints and a note on dedup ("same inputs return the same artifact_id; download without regenerating")
- [ ] 6.2 Verify the deployed pod has MinIO env (`minio_host`, `minio_root_user`, `minio_root_password`, `MINIO_BUCKET`); merge to main, bump `deploy/deployment.yaml` image tag, commit, let ArgoCD selfHeal; verify `POST /api/contracts/sale/generate-stored` returns an artifact_id and `GET /api/contracts/artifacts/{id}/download?format=docx` streams the file on `http://23.144.68.246:30820`
