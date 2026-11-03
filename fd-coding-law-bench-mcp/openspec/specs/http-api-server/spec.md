## ADDED Requirements

### Requirement: FastAPI application with async HTTP endpoints

The system SHALL provide a FastAPI-based HTTP server that exposes contract generation capabilities as REST endpoints with true async request handling.

#### Scenario: Server startup and health check
- **WHEN** the API server starts via `uvicorn` or equivalent ASGI server
- **THEN** it binds to the configured host:port (default 0.0.0.0:8000) and serves `/health` endpoint returning `{"status": "healthy"}`

#### Scenario: Async request handling
- **WHEN** multiple concurrent HTTP requests arrive
- **THEN** each request is handled asynchronously without blocking others, using FastAPI's async route handlers

#### Scenario: OpenAPI documentation auto-generation
- **WHEN** server is running
- **THEN** Swagger UI is accessible at `/docs` and ReDoc at `/redoc`, both auto-generated from route definitions and Pydantic models


### Requirement: Contract content endpoint

The system SHALL expose `POST /contracts/content` that returns assembled contract content without file I/O.

#### Scenario: Markdown content request
- **WHEN** client sends `POST /contracts/content` with `{"contract_type": "sale", "format": "markdown"}`
- **THEN** response is `200 OK` with `{"body_text": "...", "slots": [...], "instructions": [...], "law_refs": [...]}` and no file paths

#### Scenario: Tag-based assembly
- **WHEN** client sends `POST /contracts/content` with `{"contract_type": "sale", "tags": {"scenario": "农产品买卖", "stance": "balanced"}}`
- **THEN** response body_text reflects correct override hierarchy (custom > tagged > base) for the specified tags

#### Scenario: Unknown contract type error
- **WHEN** client requests unknown contract_type
- **THEN** response is `404 Not Found` with standardized error structure `{"error": {"type": "NotFoundError", "message": "..."}}`


### Requirement: Batch contract generation endpoint

The system SHALL expose `POST /contracts/batch` that generates multiple contracts in parallel.

#### Scenario: Explicit combination list
- **WHEN** client sends `POST /contracts/batch` with `{"contract_type": "sale", "tag_combinations": [{"scenario": "农产品买卖"}, {"stance": "pro_a"}]}`
- **THEN** all contracts are generated concurrently and response includes `{"results": [...], "success_count": N, "failure_count": M}`

#### Scenario: Auto-enumerate with warning
- **WHEN** client sends `POST /contracts/batch` with `{"contract_type": "sale", "enumerate_all": true}` and estimated combinations >1000
- **THEN** response includes `"combinatorial_warning": true` and suggests using explicit list

#### Scenario: Partial failure handling
- **WHEN** one contract in batch fails (coherence error, missing tags)
- **THEN** subsequent contracts continue generating and failed item includes `"success": false` with error details


### Requirement: Contract type catalog endpoints

The system SHALL expose `GET /contracts/types` and `GET /contracts/types/{type}` for metadata queries.

#### Scenario: List all contract types
- **WHEN** client sends `GET /contracts/types`
- **THEN** response is sorted list of `{"key": "sale", "zh_name": "买卖合同", "slot_count": 12, "total_base_clauses": N, ...}`

#### Scenario: Get single type metadata
- **WHEN** client sends `GET /contracts/types/sale`
- **THEN** response includes `{"key": "sale", "zh_name": "买卖合同", "universal_dims": {...}, "type_specific_dims": {...}, "scenarios": [...]}`

#### Scenario: Cache bypass with refresh parameter
- **WHEN** client sends `GET /contracts/types?refresh=true`
- **THEN** response bypasses 5-minute TTL cache and reloads from database


### Requirement: Tag combination enumeration endpoint

The system SHALL expose `GET /tags/combinations/{type}` that enumerates valid tag combinations.

#### Scenario: Basic enumeration
- **WHEN** client sends `GET /tags/combinations/sale`
- **THEN** response includes `{"combinations": [{"tags": {...}, "has_tagged_clauses": bool, ...}], "estimated_combinations": N}`

#### Scenario: Filter by clause coverage
- **WHEN** client sends `GET /tags/combinations/sale?filter_by_clause_coverage=true`
- **THEN** response excludes combinations with no tagged clauses (only base fallback)

#### Scenario: Combinatorial explosion warning
- **WHEN** estimated combinations exceed 1000
- **THEN** response includes `"combinatorial_warning": true`


### Requirement: Tag validation endpoint

The system SHALL expose `POST /tags/validate` for dry-run tag validation.

#### Scenario: Valid tags
- **WHEN** client sends `POST /tags/validate` with `{"tags": {"stance": "pro_a", "scenario": "农产品买卖"}, "contract_type": "sale"}`
- **THEN** response is `200 OK` with cleaned tag dict `{"stance": "pro_a", "scenario": "农产品买卖"}`

#### Scenario: Invalid tag value
- **WHEN** client sends invalid tag value (e.g., `{"stance": "invalid"}`)
- **THEN** response is `422 Unprocessable Entity` with error details naming the dim, bad value, and allowed set

#### Scenario: Unknown keys dropped
- **WHEN** client sends tags with unknown keys (e.g., `{"mood": "happy"}`)
- **THEN** response drops unknown keys and returns only valid tags


### Requirement: Standardized error response format

The system SHALL return consistent error structures across all endpoints.

#### Scenario: Error response structure
- **WHEN** any endpoint returns an error (4xx or 5xx)
- **THEN** response body is `{"success": false, "trace_id": "uuid", "error": {"type": "...", "message": "...", "details": {...}}}`

#### Scenario: Trace ID for debugging
- **WHEN** error occurs
- **THEN** `trace_id` is auto-generated UUID (or uses client-provided value) for log correlation

#### Scenario: Validation error details
- **WHEN** Pydantic validation fails (422)
- **THEN** error details include field-level validation messages


### Requirement: CORS support for web frontend integration

The system SHALL support Cross-Origin Resource Sharing (CORS) for browser-based clients.

#### Scenario: CORS preflight request
- **WHEN** browser sends OPTIONS request to any endpoint
- **THEN** response includes `Access-Control-Allow-Origin`, `Access-Control-Allow-Methods`, `Access-Control-Allow-Headers` headers

#### Scenario: Configurable allowed origins
- **WHEN** server starts with `CORS_ORIGINS=["http://localhost:3000", "https://app.example.com"]`
- **THEN** only those origins are allowed; others are rejected
