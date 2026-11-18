## Context

**Current State:**
- The HTTP API server (`async-api-server`) is implemented and tested (56 tests passing).
- 6 functional endpoints + health/docs exist, defined in `api/routes/contracts.py` and `api/routes/tags.py`.
- Request/response shapes live in `api/schemas.py` as Pydantic models.
- `docs/api-server.md` is a setup/configuration guide, not an endpoint reference.
- Auto-generated OpenAPI is available at `/openapi.json` + `/docs` (Swagger) when the server runs, but there's no offline, human-readable reference.

**Constraints:**
- Documentation must be accurate to the implemented schemas (field-for-field).
- No code changes - this is docs-only.
- Markdown is the format (consistent with existing `docs/`).

---

## Goals / Non-Goals

**Goals:**
1. A single canonical API reference (`docs/api-reference.md`) covering every endpoint, schema, error, and example.
2. A tag vocabulary reference (`docs/tag-vocabulary.md`) so callers know valid tag values offline.
3. Cross-link the existing setup guide and live Swagger.
4. Every curl example runnable against a locally-started server.

**Non-Goals:**
1. Generate docs from code automatically (static-site generators, mkdocs) - hand-written Markdown only.
2. Document the MCP tool layer (already covered by `docs/async-contract-api.md`).
3. Change any API behavior or schema.
4. Provide Postman/Insomnia collections (OpenAPI export already covers this).

---

## Decisions

### Decision 1: Two documents, not one

**Choice:** Split into `docs/api-reference.md` (endpoints + schemas + errors) and `docs/tag-vocabulary.md` (tag dims + contract types).

**Rationale:** The tag vocabulary + 43 contract types is large reference data that's reused across endpoints. Keeping it separate avoids bloating the endpoint reference and lets the tag doc be linked from the request-schema sections. The contract type catalog (43 types) goes in the tag-vocabulary doc since `contract_type` is a tag-adjacent enum.

**Alternatives Considered:**
- **One giant doc:** Harder to navigate, slower to load -> Rejected
- **Per-endpoint files:** Over-fragmented for 7 endpoints -> Rejected

### Decision 2: Hand-written from `api/schemas.py`, not generated

**Choice:** Author the schema tables by hand, transcribing directly from the Pydantic models.

**Rationale:** The schemas are stable and small (~12 models). Hand-writing gives clean, browsable tables with Chinese-aware descriptions. Auto-generation (e.g. from OpenAPI JSON) would require a running server and produce verbose output. A reviewer can diff the doc tables against `schemas.py` to verify accuracy (this is an explicit spec scenario).

**Alternatives Considered:**
- **Generate from OpenAPI:** Requires running server, verbose, hard to add curl examples inline -> Rejected
- **mkdocs-material site:** Overkill for a single project; adds build dependency -> Rejected

### Decision 3: curl as the canonical example format

**Choice:** Every endpoint gets a `curl` example; no language-specific SDK examples.

**Rationale:** curl is universal, copy-pasteable, and needs no SDK. The Chinese tag values (e.g. `农产品买卖`) are demonstrated in curl with proper JSON escaping, which is the trickiest part for callers. Python/JS snippets add maintenance burden without much value over curl + the JSON body tables.

**Alternatives Considered:**
- **Python requests examples:** Nice but redundant with curl + schema tables -> Rejected
- **Multiple languages:** Maintenance burden, not requested -> Rejected

### Decision 4: Per-endpoint section structure

**Choice:** Each endpoint section follows a fixed template:

```
### METHOD /path

<purpose>

| Auth | Rate limit | Public |
|------|-----------|--------|
| ...  | ...       | ...    |

**Request body** (table or "none")

**Example request** (curl)

**Response** (status + body table)

**Example response** (JSON)

**Errors** (status codes specific to this endpoint)
```

**Rationale:** A fixed structure makes the doc scannable and ensures no endpoint is missing a section. The auth/rate-limit/public mini-table answers the three most common "can I call this?" questions up front.

### Decision 5: Error catalog as a shared section, not repeated per endpoint

**Choice:** One "Error Catalog" section documents 401/403/404/422/429/500 with the standardized `ErrorResponse` shape; each endpoint section links to it and only lists the codes it can specifically return.

**Rationale:** The error *shape* is identical everywhere (`{error, message, details, trace_id}`); only the *codes* and *triggers* vary. Repeating the full shape per endpoint would bloat the doc. Endpoints list their specific codes; the catalog explains each.

---

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|------|--------|------------|
| Docs drift from schemas as code changes | Medium | Spec includes a "field accuracy" scenario; reviewer diffs tables vs `schemas.py` on any schema change |
| Chinese tag values render oddly in some markdown viewers | Low | Use UTF-8; curl examples show raw Chinese in JSON (works with modern shells) |
| 43-type catalog is long | Low | Put it in its own section with a compact two-column table |
| curl examples assume server running on :8000 | Low | State the assumption + link to setup guide at the top |

---

## Migration Plan

N/A - documentation only, no migration. New docs are additive; existing `docs/api-server.md` gets a one-line cross-link added at the top.

---

## Open Questions

1. **Should the tag-vocabulary doc enumerate type-specific dims for all 43 types?** No - only the high-variation types (sale, lease, employment + a few) as examples; the rest can be queried via `GET /tags/combinations/{type}`. Documenting all 43 would bloat the file and drift as dims are added.
2. **Versioning the API reference?** Not needed yet; the API has no `/v1` prefix and is pre-1.0. Add a version header to the doc when the API version bumps.
