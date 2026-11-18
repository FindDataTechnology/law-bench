## ADDED Requirements

### Requirement: Contract Artifacts Table
The system SHALL maintain a `contract_artifacts` table created by `ensure_schema()` with columns: `id` (serial PK), `contract_type` (text, not null), `scenario` (text, nullable), `stance` (text, nullable), `custom_clause_ids` (jsonb, nullable), `body_hash` (text, not null), `body_text` (text, not null), `slots` (jsonb, not null), `docx_key` (text, nullable), `pdf_key` (text, nullable), `minio_bucket` (text, not null), `created_at` (timestamptz, not null), `updated_at` (timestamptz, not null). There SHALL be a unique constraint on `body_hash`.

#### Scenario: Table is created by ensure_schema
- **WHEN** `ensure_schema()` runs against a fresh database
- **THEN** the `contract_artifacts` table exists with all listed columns and a unique index on `body_hash`

### Requirement: Generate-and-Store Endpoint
The system SHALL expose `POST /api/contracts/{contract_type}/generate-stored` accepting a JSON body `{scenario?, stance?, custom_clause_ids?, format}` where `format` is `"docx"` (default), `"pdf"`, `"both"`, or `"markdown"`. The endpoint SHALL bifurcate on whether tags are supplied:

- **By tag** (`scenario` and/or `stance` and/or `custom_clause_ids` given): assemble a single contract variant via `generate_contract_assembled`, upload the rendered docx/pdf to MinIO under `MINIO_ARTIFACTS_PREFIX` with key `{prefix}{contract_type}/{artifact_id}.{ext}`, record a `contract_artifacts` row, and return `{artifact_id, docx_url, pdf_url, body_text, slots, reused}`. A coherence-gate failure SHALL produce 422.
- **By contract type** (no tags): generate **every** scenario x stance x base combination for the type (enumerating distinct `scenario` values from tagged clauses and `stance` values from custom clauses), store each via the by-tag path, and return a summary `{contract_type, format, artifacts: [{artifact_id, scenario, stance, docx_url, pdf_url, reused}], count, new, reused, failed, failures}`. Per-combo coherence failures are reported in `failures` (not 422).

In both paths `docx_url`/`pdf_url` are the download endpoints (`/api/contracts/artifacts/{id}/download?format=...`) or `null` when that format was not produced. For `format: "markdown"` no file is uploaded and `docx_key`/`pdf_key` stay null (the row still records `body_text`/`body_hash`). An unknown contract type SHALL produce 404. It SHALL be documented in `/api/docs`.

#### Scenario: By type generates all combinations
- **WHEN** `POST /api/contracts/sale/generate-stored` is called with `{}`
- **THEN** it returns 200 with a summary object whose `artifacts` is a list (one entry per distinct combination), each entry has `artifact_id`, `scenario`, `stance`, and `docx_url` a `/api/contracts/artifacts/{id}/download?format=docx` URL; `count` equals `len(artifacts)`

#### Scenario: By tag generates a single variant
- **WHEN** `POST /api/contracts/sale/generate-stored` is called with `{"scenario": "生鲜乳购销"}`
- **THEN** it returns 200 with a single-variant object `{artifact_id, docx_url, pdf_url, body_text, slots, reused}` (no `artifacts` list), and the assembled `body_text` reflects the scenario's tagged clause overrides

#### Scenario: Generate markdown stores the body without a file
- **WHEN** `POST /api/contracts/sale/generate-stored` is called with `{"format": "markdown"}`
- **THEN** it returns 200 with a summary whose `artifacts[0]` has `docx_url`/`pdf_url` both null; the `contract_artifacts` row has null `docx_key`/`pdf_key`

#### Scenario: Generate both formats
- **WHEN** `POST /api/contracts/sale/generate-stored` is called with `{"format": "both"}`
- **THEN** it returns 200 with `artifacts[0]` having both `docx_url` and `pdf_url` non-null, and the row has non-null `docx_key` and `pdf_key`

#### Scenario: Unknown contract type returns 404
- **WHEN** `POST /api/contracts/does_not_exist/generate-stored` is called with `{}`
- **THEN** it returns 404

#### Scenario: Coherence failure returns 422 (by-tag)
- **WHEN** `POST /api/contracts/sale/generate-stored` is called with `{"scenario": "..."}` and the clause selection drops a canonical base section
- **THEN** it returns 422 with a diagnostic `{"detail": ...}` naming the failing check

### Requirement: Content-Addressed Dedup
The system SHALL compute `body_hash = md5(body_text)` for every generated contract. Before inserting, it SHALL `SELECT` by `body_hash`. If a row exists: it is reused (`reused: true` in the response), and for each requested format whose key is null on the existing row, the system SHALL generate+upload that format and update the row; already-stored formats are not regenerated or re-uploaded. If no row exists, it inserts a new one (`reused: false`). In the by-type (all-combinations) path, dedup applies per combination, so combinations that produce the same body collapse to one artifact.

#### Scenario: Same inputs return the same artifact id
- **WHEN** `POST /api/contracts/sale/generate-stored` is called twice with `{"scenario": "生鲜乳购销", "format": "docx"}`
- **THEN** both responses return the same `artifact_id`; the second has `reused: true`; no new MinIO object is uploaded on the second call

#### Scenario: Missing format is filled on an existing artifact
- **WHEN** `POST /api/contracts/sale/generate-stored` is called with `{"scenario": "生鲜乳购销", "format": "docx"}`, then again with `{"scenario": "生鲜乳购销", "format": "pdf"}`
- **THEN** both responses return the same `artifact_id`; the second returns `pdf_url` non-null and the row now has both `docx_key` and `pdf_key` non-null

### Requirement: List Artifacts Endpoint
The system SHALL expose `GET /api/contracts/artifacts` returning a JSON list of artifact metadata rows (excluding `body_text`), newest first, optionally filtered by `?contract_type=`. Each row SHALL include `id, contract_type, scenario, stance, custom_clause_ids, body_hash, slots, docx_key, pdf_key, created_at, updated_at`. It SHALL be documented in `/api/docs`.

#### Scenario: List artifacts filtered by type
- **WHEN** `GET /api/contracts/artifacts?contract_type=sale` is called after storing a sale artifact
- **THEN** it returns 200 with a non-empty list whose entries each have `contract_type == "sale"` and no `body_text` field

### Requirement: Artifact Metadata Endpoint
The system SHALL expose `GET /api/contracts/artifacts/{id}` returning the full artifact row including `body_text`. A non-existent id SHALL produce 404. It SHALL be documented in `/api/docs`.

#### Scenario: Fetch artifact metadata
- **WHEN** `GET /api/contracts/artifacts/{id}` is called with an existing id
- **THEN** it returns 200 with `id`, `contract_type`, `body_text`, `slots`, `docx_key`, `pdf_key`, and `created_at`

#### Scenario: Unknown artifact id returns 404
- **WHEN** `GET /api/contracts/artifacts/999999` is called
- **THEN** it returns 404

### Requirement: Artifact Download Endpoint
The system SHALL expose `GET /api/contracts/artifacts/{id}/download` accepting a `format` query param (`docx` or `pdf`). It SHALL stream the file from MinIO to the client with the correct `Content-Type` (`application/vnd.openxmlformats-officedocument.wordprocessingml.document` for docx, `application/pdf` for pdf) and a `Content-Disposition: attachment` header. A non-existent id, or an id without the requested format stored, SHALL produce 404. It SHALL be documented in `/api/docs`.

#### Scenario: Download a stored docx
- **WHEN** `GET /api/contracts/artifacts/{id}/download?format=docx` is called for an artifact with `docx_key` non-null
- **THEN** it returns 200 with the docx content-type and a non-empty body

#### Scenario: Download a missing format returns 404
- **WHEN** `GET /api/contracts/artifacts/{id}/download?format=pdf` is called for an artifact with `pdf_key` null
- **THEN** it returns 404

#### Scenario: Unknown artifact id returns 404
- **WHEN** `GET /api/contracts/artifacts/999999/download?format=docx` is called
- **THEN** it returns 404

### Requirement: MinIO Upload
The system SHALL upload generated docx/pdf files to the configured MinIO bucket (`MINIO_BUCKET`) under the `MINIO_ARTIFACTS_PREFIX` (default `artifacts/`) with key `{prefix}{contract_type}/{artifact_id}.{ext}`. It SHALL use the native `minio` SDK with `MINIO_ENDPOINT`/`MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY`/`MINIO_SECURE`, and SHALL bypass proxy env (`NO_PROXY=*`) to avoid the macOS/proxy 502.

#### Scenario: Generated file is uploaded to MinIO
- **WHEN** `POST /api/contracts/sale/generate-stored` is called with `{"format": "docx"}`
- **THEN** the returned artifact's `docx_key` is `artifacts/sale/{artifact_id}.docx` and the object exists in `MINIO_BUCKET`

### Requirement: MCP Generate-Stored and Download Tools
The system SHALL expose MCP tools: `contract_generate_stored(contract_type, format="docx", tags=None, stance=None, custom_clause_ids=None)` and `contract_download(artifact_id, format=None)`. `contract_generate_stored` SHALL mirror the HTTP endpoint's bifurcation: with `tags`/`stance`/`custom_clause_ids` it returns the single-variant `{artifact_id, docx_url, pdf_url, body_text, slots, reused}`; with no tags it returns the all-combinations summary `{contract_type, format, artifacts: [...], count, new, reused, failed, failures}`. `contract_download` returns the artifact metadata + the HTTP download URL(s). Both SHALL be registered with the `contracts` tag.

#### Scenario: contract_generate_stored by type returns the all-combos summary
- **WHEN** `contract_generate_stored("sale", format="docx")` is called (no tags)
- **THEN** it returns a summary object with `artifacts` (a list), `count`, `new`, `reused`, and `failed`

#### Scenario: contract_generate_stored by tag returns a single variant
- **WHEN** `contract_generate_stored("sale", tags={"scenario": "生鲜乳购销"})` is called
- **THEN** it returns an object with `artifact_id` (int), `docx_url` (a `/api/contracts/artifacts/{id}/download?format=docx` URL), `body_text` (non-empty), and `reused` (bool)

#### Scenario: contract_download returns metadata + URL
- **WHEN** `contract_download(artifact_id)` is called for an existing artifact
- **THEN** it returns the artifact metadata and a `download_url` pointing at the HTTP download endpoint

### Requirement: Settings and Schema Wiring
The system SHALL add `MINIO_ARTIFACTS_PREFIX` (default `artifacts/`) to `src/settings.py` and the `contract_artifacts` DDL to `src/eval/store.py` so `ensure_schema()` creates it. The new HTTP endpoints SHALL be included in the `contract_context` router (or a new router wired in `src/web/app.py`) and appear in `/api/docs`.

#### Scenario: New endpoints appear in the OpenAPI schema
- **WHEN** `GET /openapi.json` is fetched
- **THEN** the paths include `POST /api/contracts/{contract_type}/generate-stored`, `GET /api/contracts/artifacts`, `GET /api/contracts/artifacts/{id}`, and `GET /api/contracts/artifacts/{id}/download`

#### Scenario: MINIO_ARTIFACTS_PREFIX defaults to artifacts/
- **WHEN** `MINIO_ARTIFACTS_PREFIX` is unset in the environment
- **THEN** `src.settings.MINIO_ARTIFACTS_PREFIX == "artifacts/"`
