## Context

The repo can already assemble and render a contract (`src.clauses.assemble.generate_contract_assembled` -> `{docx_path, pdf_path, body_text, ...}`, writing files to `output/contracts/`), and the just-added `contract-context-api` exposes that over HTTP (`POST /api/contracts/{type}/generate` returns local file URLs). MinIO is already in the stack as an S3-compatible document source for RAG (`src/search/minio_source.py`, settings `MINIO_ENDPOINT`/`MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY`/`MINIO_SECURE`/`MINIO_BUCKET`="scraw-law-contracts", prefixes `templates/`+`drafts/`; both the `minio` SDK 7.2.20 and `boto3` are installed). The DB layer centralizes table DDL in `src/eval/store.py` (created by `ensure_schema()`) and uses a borrowed-connection model (`src.eval.db.connect`). The MCP server (`fd-coding-law-bench-mcp/`) registers tools via `@mcp.tool(tags={"contracts"})` and already has `contract_generate` wrapping the same assembly. What is missing: generation results are ephemeral local files with no DB record and no object storage - re-fetching means regenerating, files don't survive pod restarts, and there is no "list/download previously generated contracts" path. Constraints: no new Python deps; reuse the existing MinIO bucket + creds; the assembly model and coherence gate are stable and must not change; the deployed pod already has MinIO env (RAG path uses it).

## Goals / Non-Goals

**Goals:**
- Generate a contract by type (+ optional tags: scenario/stance/custom_clause_ids), upload the docx/pdf to MinIO, and record it in a `contract_artifacts` DB table.
- Content-addressed dedup: identical inputs (same assembled body) return the same artifact id; missing formats are filled in, already-stored formats are reused - so a consumer can download without regenerating.
- Download by artifact id: a metadata endpoint and a streaming download endpoint (server proxies from MinIO).
- Both surfaces: HTTP endpoints under `/api/contracts` (documented in `/api/docs`) and MCP tools (`contract_generate_stored`, `contract_download`).

**Non-Goals:**
- Presigned URLs (v1 uses server proxy-stream; presigned is a follow-up if server load matters).
- Artifact versioning/history (dedup collapses identical inputs to one row).
- Deleting or expiring artifacts (lifecycle policy is a follow-up).
- Migrating the ephemeral local-file `POST /generate` to use storage - it stays as a quick local path.
- Storing the contract in any format other than docx/pdf (markdown is already returned in `body_text`).
- Any change to `generate_contract_assembled`, the coherence gate, the assembly precedence, or `document-generation`.

## Decisions

### D1: Native `minio` SDK, not boto3
**Choice**: Use `from minio import Minio` with the existing `MINIO_*` settings.
**Rationale**: The `minio` SDK is native to MinIO (no AWS surface area), is already installed (7.2.20), and matches the bucket/endpoint settings already used by `src/search`. boto3 is available but heavier and AWS-oriented.
**Alternatives**: boto3 (works, but more config; the existing reader uses llama_index's MinioReader, not boto3, so no boto3 precedent to follow).

### D2: One `contract_artifacts` row per contract body, with per-format MinIO keys
**Choice**: The table has one row per distinct assembled body, keyed by `body_hash` (md5 of `body_text`), with nullable `docx_key` and `pdf_key` columns. A `format` request fills the corresponding key(s).
**Rationale**: An artifact is "this contract" (one body) that may have docx and/or pdf representations. One row per body makes dedup natural (unique on `body_hash`) and lets a later request for a different format reuse the existing body. Storing `body_text` in the row lets the metadata endpoint return the text without a MinIO round-trip (contract bodies are small, ~2-10 KB).
**Alternatives**: One row per file (one row for docx, another for pdf) - simpler inserts but loses the "this contract has both formats" relationship and complicates dedup across formats. A `formats JSONB` array - less queryable than two nullable columns.

### D3: Content-addressed dedup via `body_hash`
**Choice**: On `generate-stored`: assemble the body, compute `body_hash = md5(body_text)`. `SELECT ... WHERE body_hash = %s`. If found: for each requested format, if its key is null, generate+upload that format and update the row; set `reused=true`. If not found: generate all requested formats, upload, insert. Return the (existing or new) `artifact_id`.
**Rationale**: The assembled body is deterministic given (contract_type, scenario, stance, custom_clause_ids), so the hash is a stable identity. This directly fulfills "download directly, so do not need generate" - the second call for the same inputs is a no-op that returns the existing id + URLs. It also avoids re-uploading identical bytes to MinIO.
**Alternatives**: Always generate + insert (new id each time) - rejected, defeats the "no need to regenerate" goal and accumulates duplicate objects. Dedup on (type+tags+format) input tuple - rejected, brittle if tag storage evolves; the body hash is the true content identity.

### D4: Separate `generate-stored` endpoint; ephemeral `generate` stays
**Choice**: Add `POST /api/contracts/{type}/generate-stored` (MinIO + DB). The existing `POST /api/contracts/{type}/generate` (local file) is unchanged. The stored endpoint bifurcates (see D11): by-tag -> single variant; by-type (no tags) -> all combinations.
**Rationale**: The ephemeral path is useful for quick local generation and tests (no MinIO/DB needed). The stored path has different semantics (dedup, persistence, returns `artifact_id`). Merging them via a `?store=true` flag would bloat one endpoint's contract. Two endpoints, one router.
**Alternatives**: A `?store=true` flag on `generate` (rejected - mixed return shape); replace `generate` with the stored version (rejected - breaks the just-shipped contract-context-api spec and removes the cheap local path).

### D11: By-type generates all combinations; by-tag generates one variant
**Choice**: `generate-stored` (HTTP + MCP) bifurcates on whether tags are supplied. With `scenario`/`stance`/`custom_clause_ids` -> `generate_stored` (single variant, returns `{artifact_id, ...}`). With no tags -> `generate_all_stored` enumerates every scenario x stance x base combination for the type and stores each, returning a summary `{artifacts: [...], count, new, reused, failed, failures}`. `generate_stored` (single) is unchanged; `generate_all_stored` is a new service function that loops over combinations calling `generate_stored`.
**Rationale**: The user wants "by contract type" to mean "generate the whole tag space for that type and upload it all" - not just the base 母版 (the old behavior). By-tag stays single-variant (a consumer asking for a specific scenario wants one contract, not 460). Bifurcating on tag presence keeps one endpoint with two clear modes; the return shape differs (dict vs summary) but both are JSON objects. Per-combo coherence failures are reported in `failures` rather than 422 (one bad combination shouldn't abort the whole type).
**Alternatives**: A separate `generate-all-stored` endpoint (rejected - the user asked to modify the existing interface, and two endpoints for "by type" vs "by tag" is less discoverable); always return a list (rejected - breaks the single-variant response shape and its tests).

### D5: Download via server proxy-stream, not presigned URLs
**Choice**: `GET /api/contracts/artifacts/{id}/download?format=docx` streams the object from MinIO through the server to the client (`StreamingResponse`). The server holds the MinIO creds; the client gets a normal HTTP download.
**Rationale**: Uniform API (clients don't need MinIO creds or to handle URL expiry), and the server stays the single entry point. Contract files are small (tens of KB), so proxying is cheap.
**Alternatives**: Return a presigned MinIO URL (offloads bytes from the server, but exposes MinIO to clients and needs URL-expiry handling) - tracked as a follow-up if proxy load matters.

### D6: MinIO key scheme + new prefix
**Choice**: Object keys are `artifacts/{contract_type}/{artifact_id}.{ext}` under the existing `MINIO_BUCKET` (`scraw-law-contracts`). New setting `MINIO_ARTIFACTS_PREFIX` (default `artifacts/`).
**Rationale**: Keyed by `artifact_id` (a DB serial) for uniqueness and traceability; grouped by `contract_type` for browsing. Reuses the existing bucket - no new bucket to provision. A dedicated prefix keeps generated artifacts separate from `templates/` and `drafts/`.
**Alternatives**: Key by `body_hash` (content-addressed) - workable but opaque; key by `{type}/{scenario}/{format}` - collides on stance/custom selection differences.

### D7: MCP tools return metadata + HTTP download URLs
**Choice**: `contract_generate_stored(...)` returns `{artifact_id, docx_url, pdf_url, body_text, reused}` (URLs are the HTTP download endpoints). `contract_download(artifact_id, format=None)` returns artifact metadata + the download URL(s); the agent fetches bytes over HTTP.
**Rationale**: MCP tools return structured data, not binary streams. Returning the HTTP download URL lets an agent or downstream client fetch the file directly. The body text is included so an agent can use the contract content without a second round trip.
**Alternatives**: Have MCP write the file to a local path and return the path (rejected - the agent may run on a different host than the server); return base64 bytes (rejected - bloats the MCP response).

### D8: Storage service location - `src/contracts/artifacts.py`
**Choice**: New module `src/contracts/artifacts.py` holding the MinIO client + the `generate_stored`/`get_artifact`/`list_artifacts`/`download` service functions. The HTTP routes and MCP tools are thin wrappers over it.
**Rationale**: The service is contract-artifact-centric (it wraps `generate_contract_assembled`), so it belongs in `src/contracts/` alongside `generator.py`/`slots.py`. Both the web layer and MCP layer import it, keeping them in sync. The DB row functions follow the `src.clauses.store` pattern (borrowed `connect`, `ensure_schema`).
**Alternatives**: Put it in `src/clauses/` (assembly lives there) - rejected, the artifact is a contract deliverable, not a clause; `src/eval/store.py` for DB - rejected, that's the schema/DDL module, the CRUD belongs with the domain.

### D9: Reuse `generate_contract_assembled`, upload its files, no behavior change
**Choice**: The service calls `generate_contract_assembled(type, scenario=, stance=, custom_clause_ids=, format=, db=db)` exactly as the ephemeral endpoint does, then uploads the returned `docx_path`/`pdf_path` to MinIO and records the row. Local files under `output/contracts/` are left in place (the ephemeral path may serve them).
**Rationale**: Single generation code path - the stored and ephemeral endpoints produce identical bytes. No risk of divergence.
**Alternatives**: Add an in-memory render mode to `generate_contract_assembled` to avoid touching disk (rejected - out of scope, changes a stable function; disk is fine).

### D10: `NO_PROXY` workaround for the MinIO client
**Choice**: Set `os.environ.setdefault("NO_PROXY", "*")` in the artifacts module (as `src/search/minio_source.py` does for botocore) so the `minio` client bypasses the macOS/proxy env that 502s against MinIO.
**Rationale**: Same host/proxy environment that bit the RAG path; the native `minio` SDK honors `HTTP_PROXY`/`HTTPS_PROXY` too. Belt-and-suspenders reuse of the known fix.
**Alternatives**: Configure the `minio` client with an explicit http_client ignoring proxies - more code, same effect.
