# Law Bench Contract Generation API Reference

Version 0.1.0 · Async REST API for generating legal contracts via tag-driven assembly.

This is the canonical reference for every endpoint, request/response schema, and
error in the Law Bench HTTP API. For server setup/configuration, see
[API Server Setup](api-server.md). For valid tag values and contract types, see
[Tag Vocabulary Reference](tag-vocabulary.md). An interactive Swagger UI is
available at `/docs` and ReDoc at `/redoc` when the server is running.

---

## Table of Contents

- [Getting Started](#getting-started)
- [Authentication](#authentication)
- [Rate Limiting](#rate-limiting)
- [Endpoints](#endpoints)
  - [POST /contracts/content](#post-contractscontent)
  - [POST /contracts/batch](#post-contractsbatch)
  - [GET /contracts/types](#get-contractstypes)
  - [GET /contracts/types/{contract_type}](#get-contractstypescontract_type)
  - [GET /tags/combinations/{contract_type}](#get-tagscombinationscontract_type)
  - [POST /tags/validate](#post-tagsvalidate)
  - [GET /health](#get-health)
- [Schemas](#schemas)
  - [Request Schemas](#request-schemas)
  - [Response Schemas](#response-schemas)
- [Error Catalog](#error-catalog)

---

## Getting Started

**Base URL:** `http://localhost:8000` (default; configurable via `HOST`/`PORT`)

**Content type:** All request bodies are `application/json`. All responses are
`application/json` (except `/docs` and `/redoc`, which are HTML).

**Quick test:**

```bash
# Start the server (see api-server.md for details)
# uvicorn fd_coding_law_bench_mcp.api.main:app --port 8000

# Health check
curl http://localhost:8000/health
# -> {"status":"healthy"}

# Generate a sale contract (markdown, no file I/O)
curl -X POST http://localhost:8000/contracts/content \
  -H "Content-Type: application/json" \
  -d '{"contract_type": "sale", "format": "markdown"}'
```

---

## Authentication

Authentication is **optional** and **disabled by default**. Enable it by setting
environment variables (see [API Server Setup](api-server.md)):

```bash
export API_KEY_ENABLED=true
export API_KEYS="your-secret-key-1,your-secret-key-2"
```

When enabled, every non-public endpoint requires an `X-API-Key` header:

```bash
curl -H "X-API-Key: your-secret-key-1" http://localhost:8000/contracts/types
```

**Public endpoints** (never require auth): `/health`, `/docs`, `/redoc`,
`/openapi.json`.

See the [Error Catalog](#error-catalog) for 401/403 responses.

---

## Rate Limiting

Rate limiting is **enabled by default** at 100 requests / 60 seconds per client
(configurable via `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW`). Backends:
in-memory (default) or Redis (`RATE_LIMIT_BACKEND=redis`, `REDIS_URL=...`).

When a limit is exceeded, the API returns `429 Too Many Requests` (see
[Error Catalog](#error-catalog)).

---

## Endpoints

### POST /contracts/content

Generate a single contract's content from tags. The fastest path is
`format="markdown"`, which returns the assembled body text **without any file
I/O**.

| Auth required | Rate limit | Public |
|---------------|------------|--------|
| Optional (when `API_KEY_ENABLED=true`) | Default tier | No |

**Request body:** [ContractContentRequest](#contractcontentrequest)

**Example request:**

```bash
curl -X POST http://localhost:8000/contracts/content \
  -H "Content-Type: application/json" \
  -d '{
    "contract_type": "sale",
    "tags": {"scenario": "农产品买卖", "stance": "balanced"},
    "format": "markdown"
  }'
```

**Response:** `200 OK` — [ContractContentResponse](#contractcontentresponse)

**Example response:**

```json
{
  "trace_id": "a1b2c3d4-...",
  "contract_type": "sale",
  "format": "markdown",
  "body_text": "## 当事人\n\n甲方（出卖人）：{{party_a}}\n...",
  "slots": ["party_a", "party_b", "subject", "amount"],
  "instructions": [
    {"name": "party_a", "label": "甲方名称", "description": "...", "example": "...", "required": true}
  ],
  "law_refs": [
    {"name": "中华人民共和国民法典", "category": "statute"}
  ],
  "tags_used": {"scenario": "农产品买卖", "stance": "balanced"}
}
```

**Errors:** `404` (unknown contract type), `422` (validation), `500` (assembly /
coherence failure). See [Error Catalog](#error-catalog).

---

### POST /contracts/batch

Generate multiple contracts in parallel across different tag combinations.
Accepts an explicit list, or auto-enumerates all valid combinations.

| Auth required | Rate limit | Public |
|---------------|------------|--------|
| Optional | Stricter (batch tier) | No |

**Request body:** [ContractBatchRequest](#contractbatchrequest)

**Example request (explicit combinations):**

```bash
curl -X POST http://localhost:8000/contracts/batch \
  -H "Content-Type: application/json" \
  -d '{
    "contract_type": "sale",
    "tag_combinations": [
      {"scenario": "农产品买卖", "stance": "pro_a"},
      {"scenario": "消费品零售", "stance": "balanced"}
    ],
    "max_concurrent": 5
  }'
```

**Example request (auto-enumerate all):**

```bash
curl -X POST http://localhost:8000/contracts/batch \
  -H "Content-Type: application/json" \
  -d '{"contract_type": "sale", "enumerate_all": true}'
```

**Response:** `200 OK` — [ContractBatchResponse](#contractbatchresponse)

**Example response (partial failure):**

```json
{
  "trace_id": "batch-trace-...",
  "contract_type": "sale",
  "total_requested": 2,
  "success_count": 1,
  "failure_count": 1,
  "results": [
    {
      "success": true,
      "tags": {"scenario": "农产品买卖", "stance": "pro_a"},
      "body_text": "## 当事人\n\n...",
      "slots": ["party_a"],
      "instructions": [],
      "law_refs": [],
      "tags_used": {}
    },
    {
      "success": false,
      "tags": {"scenario": "invalid"},
      "error": {
        "type": "CoherenceError",
        "message": "Missing required slot: party_a",
        "details": {}
      }
    }
  ],
  "combinatorial_warning": false
}
```

> **Combinatorial warning:** When `enumerate_all=true` produces more than 1000
> combinations, `combinatorial_warning` is set to `true` and a server-side
> warning is logged. Prefer explicit `tag_combinations` for large types.

**Errors:** `422` (validation), `500` (preparation failure). Individual item
failures are reported per-result, not as HTTP errors. See
[Error Catalog](#error-catalog).

---

### GET /contracts/types

List all supported contract types with clause-count statistics.

| Auth required | Rate limit | Public |
|---------------|------------|--------|
| Optional | Catalog tier (read-only) | No |

**Query parameters:** none.

**Example request:**

```bash
curl http://localhost:8000/contracts/types
```

**Response:** `200 OK` — [ContractTypeCatalogResponse](#contracttypecatalogresponse)

**Example response:**

```json
{
  "types": [
    {
      "key": "sale",
      "zh_name": "买卖合同",
      "slot_count": 12,
      "total_base_clauses": 10,
      "total_tagged_clauses": 5,
      "total_custom_clauses": 3,
      "has_scenarios": true
    }
  ],
  "total": 43
}
```

**Errors:** `500` (DB failure). See [Error Catalog](#error-catalog).

---

### GET /contracts/types/{contract_type}

Get detailed metadata for a single contract type: tag dimensions, scenarios,
and assembly readiness.

| Auth required | Rate limit | Public |
|---------------|------------|--------|
| Optional | Catalog tier | No |

**Path parameters:**

| Name | Type | Description |
|------|------|-------------|
| `contract_type` | string | Contract type key (see [Tag Vocabulary](tag-vocabulary.md#contract-type-catalog)) |

**Example request:**

```bash
curl http://localhost:8000/contracts/types/sale
```

**Response:** `200 OK` — [TypeMetadataResponse](#typemetadataresponse)

**Example response:**

```json
{
  "key": "sale",
  "zh_name": "买卖合同",
  "slot_count": 12,
  "universal_dims": {
    "stance": ["pro_a", "pro_b", "balanced"],
    "strength": ["strong", "standard", "mild"]
  },
  "type_specific_dims": {
    "risk_transfer_node": ["on_delivery", "at_port_of_shipment", "at_destination", "delivered_to_carrier"]
  },
  "scenarios": [
    {
      "name": "农产品买卖",
      "clause_count": 3,
      "has_tagged_clauses": true,
      "example_clause_ids": [7094, 7095, 7096]
    }
  ],
  "assembly_ready": true
}
```

**Errors:** `404` (unknown contract type), `500` (DB failure). See
[Error Catalog](#error-catalog).

---

### GET /tags/combinations/{contract_type}

Enumerate all valid tag combinations for a contract type as a Cartesian product
of its dimensions, enriched with clause-availability metadata.

| Auth required | Rate limit | Public |
|---------------|------------|--------|
| Optional | Default tier | No |

**Path parameters:**

| Name | Type | Description |
|------|------|-------------|
| `contract_type` | string | Contract type key |

**Query parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `filter_by_clause_coverage` | boolean | `false` | If `true`, exclude combinations with no tagged clauses |

**Example request:**

```bash
curl "http://localhost:8000/tags/combinations/sale?filter_by_clause_coverage=true"
```

**Response:** `200 OK` — [TagCombinationsResponse](#tagcombinationsresponse)

**Example response:**

```json
{
  "contract_type": "sale",
  "dimensions": ["stance", "scenario"],
  "combinations": [
    {
      "tags": {"stance": "pro_a", "scenario": "农产品买卖"},
      "has_tagged_clauses": true,
      "tagged_clause_count": 3,
      "tagged_clause_ids": [7094, 7095, 7096],
      "has_custom_clauses": true
    }
  ],
  "estimated_combinations": 18,
  "combinatorial_warning": false
}
```

> **Combinatorial warning:** `combinatorial_warning` is `true` when the
> estimated combinations exceed 1000.

**Errors:** `404` (unknown contract type), `500` (DB failure). See
[Error Catalog](#error-catalog).

---

### POST /tags/validate

Validate a tag dict against the controlled vocabulary. Returns the cleaned tags
and any validation errors. Note: a validation **failure** returns `200 OK` with
`valid: false` (not an HTTP error) — only unexpected server errors raise 5xx.

| Auth required | Rate limit | Public |
|---------------|------------|--------|
| Optional | Default tier | No |

**Request body:** [TagValidateRequest](#tagvalidaterequest)

**Example request (valid tags):**

```bash
curl -X POST http://localhost:8000/tags/validate \
  -H "Content-Type: application/json" \
  -d '{
    "tags": {"stance": "pro_a", "scenario": "农产品买卖"},
    "contract_type": "sale"
  }'
```

**Response:** `200 OK` — [TagValidateResponse](#tagvalidateresponse)

**Example response (valid):**

```json
{
  "valid": true,
  "cleaned_tags": {"stance": "pro_a", "scenario": "农产品买卖"},
  "errors": []
}
```

**Example response (invalid value):**

```json
{
  "valid": false,
  "cleaned_tags": {},
  "errors": ["invalid tag value: stance='invalid'; allowed: ['pro_a', 'pro_b', 'balanced']"]
}
```

> **Scenario leniency:** `scenario` accepts any non-empty string (it is
> LLM-suggested). Unknown keys (e.g. `{"mood": "happy"}`) are silently dropped,
> not rejected. See [Tag Vocabulary](tag-vocabulary.md).

**Errors:** `500` (unexpected server error). See [Error Catalog](#error-catalog).

---

### GET /health

Health check for load balancers and monitoring.

| Auth required | Rate limit | Public |
|---------------|------------|--------|
| Never | None | Yes |

**Example request:**

```bash
curl http://localhost:8000/health
```

**Response:** `200 OK`

```json
{"status": "healthy"}
```

---

## Schemas

All schemas are defined in `api/schemas.py`. Tables below match the Pydantic
models field-for-field.

### Request Schemas

#### ContractContentRequest

Generate a single contract's content.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `contract_type` | string | Yes | — | Contract type key (e.g. `sale`, `lease`). See [catalog](tag-vocabulary.md#contract-type-catalog). |
| `tags` | object | No | `null` | Tag dict, e.g. `{"scenario": "农产品买卖", "stance": "balanced"}`. See [Tag Vocabulary](tag-vocabulary.md). |
| `format` | enum | No | `"markdown"` | One of `markdown`, `docx`, `pdf`, `both`. `markdown` returns text only (no file I/O). |
| `include_current_tags` | boolean | No | `false` | If `true`, attach the live tag vocabulary to the response. |
| `trace_id` | string | No | `null` | Optional trace ID for request tracking. Auto-generated if omitted. |

#### ContractBatchRequest

Generate multiple contracts in parallel.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `contract_type` | string | Yes | — | Contract type key. |
| `tag_combinations` | array[object] | No | `null` | List of tag dicts to generate. If `null` and `enumerate_all=false`, the request errors. |
| `enumerate_all` | boolean | No | `false` | If `true`, auto-generate all valid tag combinations for the type. |
| `max_concurrent` | integer | No | `5` | Max parallel generation tasks. Range: 1–20. |

#### TagValidateRequest

Validate a tag dict.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `tags` | object | Yes | — | Tags to validate. |
| `contract_type` | string | No | `null` | Contract type for validation context (selects type-specific dims). |

---

### Response Schemas

#### ContractContentResponse

Returned by `POST /contracts/content`.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `trace_id` | string | Yes | — | Unique trace ID for this request. |
| `contract_type` | string | Yes | — | Contract type key. |
| `format` | string | Yes | — | Output format used. |
| `body_text` | string | Yes | — | Generated contract content (Markdown with `{{slot}}` placeholders). |
| `slots` | array[string] | No | `[]` | Slot names in the contract. |
| `instructions` | array[object] | No | `[]` | Slot-filling instructions (name/label/description/example/required). |
| `law_refs` | array[object] | No | `[]` | Referenced laws/regulations. |
| `tags_used` | object | No | `{}` | Tags actually used in generation. |
| `docx_path` | string | No | `null` | Path to DOCX file (only if `format` includes docx). |
| `pdf_path` | string | No | `null` | Path to PDF file (only if `format` includes pdf). |
| `current_tags` | object | No | `null` | Live tag vocabulary (only if `include_current_tags=true`). |

#### ContractBatchResponse

Returned by `POST /contracts/batch`.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `trace_id` | string | Yes | — | Unique trace ID for this batch. |
| `contract_type` | string | Yes | — | Contract type key. |
| `total_requested` | integer | Yes | — | Total combinations requested. |
| `success_count` | integer | Yes | — | Successful generations. |
| `failure_count` | integer | Yes | — | Failed generations. |
| `results` | array[[ContractBatchItem](#contractbatchitem)] | Yes | — | Results for each combination. |
| `combinatorial_warning` | boolean | No | `false` | `true` if >1000 combinations detected. |
| `error` | object | No | `null` | Error details if tag preparation failed. |

##### ContractBatchItem

Single item in `ContractBatchResponse.results`.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `success` | boolean | Yes | — | Whether this generation succeeded. |
| `tags` | object | Yes | — | Tags used for this generation. |
| `contract_type` | string | No | `null` | Contract type key. |
| `body_text` | string | No | `null` | Generated contract content (on success). |
| `slots` | array[string] | No | `null` | Slot names (on success). |
| `instructions` | array[object] | No | `null` | Slot-filling instructions (on success). |
| `law_refs` | array[object] | No | `null` | Referenced laws (on success). |
| `tags_used` | object | No | `null` | Tags actually used (on success). |
| `error` | object | No | `null` | Error details (type/message/details) if `success=false`. |

#### ContractTypeCatalogResponse

Returned by `GET /contracts/types`.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `types` | array[[ContractTypeCatalogItem](#contracttypecatalogitem)] | Yes | — | List of contract types. |
| `total` | integer | Yes | — | Total number of contract types. |

##### ContractTypeCatalogItem

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `key` | string | Yes | — | Contract type key. |
| `zh_name` | string | Yes | — | Chinese name. |
| `slot_count` | integer | Yes | — | Number of slots in the template. |
| `total_base_clauses` | integer | Yes | — | Number of base clauses. |
| `total_tagged_clauses` | integer | Yes | — | Number of tagged clauses. |
| `total_custom_clauses` | integer | Yes | — | Number of custom clauses. |
| `has_scenarios` | boolean | Yes | — | Whether this type has scenario-specific clauses. |

#### TypeMetadataResponse

Returned by `GET /contracts/types/{contract_type}`.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `key` | string | Yes | — | Contract type key. |
| `zh_name` | string | Yes | — | Chinese name. |
| `slot_count` | integer | Yes | — | Number of slots in the template. |
| `universal_dims` | object | Yes | — | Universal tag dimensions (dim → allowed values). |
| `type_specific_dims` | object | Yes | — | Type-specific tag dimensions (dim → allowed values). |
| `scenarios` | array[[ScenarioInfo](#scenarioinfo)] | Yes | — | Available scenarios. |
| `assembly_ready` | boolean | Yes | — | Whether this type has ≥1 assembly-ready custom clause. |

##### ScenarioInfo

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | Yes | — | Scenario name. |
| `clause_count` | integer | Yes | — | Number of clauses for this scenario. |
| `has_tagged_clauses` | boolean | Yes | — | Whether this scenario has tagged clauses. |
| `example_clause_ids` | array[integer] | No | `[]` | Example clause IDs (first 3). |

#### TagCombinationsResponse

Returned by `GET /tags/combinations/{contract_type}`.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `contract_type` | string | Yes | — | Contract type key. |
| `dimensions` | array[string] | Yes | — | Tag dimensions used in the product. |
| `combinations` | array[[TagCombinationInfo](#tagcombinationinfo)] | Yes | — | List of tag combinations. |
| `estimated_combinations` | integer | Yes | — | Total number of combinations. |
| `combinatorial_warning` | boolean | No | `false` | `true` if >1000 combinations. |

##### TagCombinationInfo

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `tags` | object | Yes | — | Tag values for this combination. |
| `has_tagged_clauses` | boolean | Yes | — | Whether tagged clauses exist. |
| `tagged_clause_count` | integer | Yes | — | Number of tagged clauses. |
| `tagged_clause_ids` | array[integer] | Yes | — | IDs of tagged clauses. |
| `has_custom_clauses` | boolean | Yes | — | Whether custom clauses exist. |

#### TagValidateResponse

Returned by `POST /tags/validate`.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `valid` | boolean | Yes | — | Whether the tags are valid. |
| `cleaned_tags` | object | Yes | — | Cleaned/normalized tags (empty on failure). |
| `errors` | array[string] | No | `[]` | Validation error messages. |

---

## Error Catalog

All errors return a standardized shape based on the
[ErrorResponse](#errorresponse) schema. Each endpoint's "Errors" note lists the
codes it can specifically return; this catalog explains each code's trigger and
shape.

### ErrorResponse

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `error` | string | Yes | — | Error type/name (e.g. `NotFoundError`, `HTTP404`). |
| `message` | string | Yes | — | Human-readable error message. |
| `details` | object | No | `null` | Additional error details. |
| `trace_id` | string | No | `null` | Trace ID for debugging. |

### 401 Unauthorized

**Trigger:** API key auth is enabled (`API_KEY_ENABLED=true`) and the request
omits the `X-API-Key` header on a non-public endpoint.

```json
{
  "error": "Unauthorized",
  "message": "API key required. Provide X-API-Key header."
}
```

### 403 Forbidden

**Trigger:** API key auth is enabled and the provided `X-API-Key` is invalid.

```json
{
  "error": "Forbidden",
  "message": "Invalid API key."
}
```

### 404 Not Found

**Trigger:** An unknown `contract_type` is passed to
`GET /contracts/types/{contract_type}` or
`GET /tags/combinations/{contract_type}`. Also returned for completely unknown
routes.

```json
{
  "error": "NotFound",
  "message": "Contract type 'unknown' not found"
}
```

### 422 Unprocessable Entity

**Trigger:** The request body fails Pydantic validation (missing required field,
wrong type, invalid enum value, `max_concurrent` out of 1–20 range).

```json
{
  "error": "ValidationError",
  "message": "Request validation failed",
  "details": {
    "validation_errors": [
      {
        "field": "body.contract_type",
        "message": "Field required",
        "type": "missing"
      }
    ]
  }
}
```

### 429 Too Many Requests

**Trigger:** The client exceeded its rate limit (default 100 requests / 60s).
Includes a `Retry-After` header.

```json
{
  "error": "RateLimitError",
  "message": "Rate limit exceeded"
}
```

### 500 Internal Server Error

**Trigger:** An unexpected exception during generation (e.g. DB connection
failure, coherence-gate failure on `POST /contracts/content`). When
`DEBUG=true`, the `details` include the exception type, message, and traceback.

```json
{
  "error": "InternalServerError",
  "message": "An unexpected error occurred",
  "details": {
    "exception_type": "CoherenceError"
  },
  "trace_id": "a1b2c3d4-..."
}
```

> **Note:** Validation *business* failures on `POST /tags/validate` (invalid
> tag values) do **not** return an HTTP error — they return `200 OK` with
> `valid: false` and an `errors` array. See [POST /tags/validate](#post-tagsvalidate).
