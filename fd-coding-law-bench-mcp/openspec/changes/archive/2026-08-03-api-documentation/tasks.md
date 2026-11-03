## 1. Endpoint Reference (docs/api-reference.md)

- [x] 1.1 Create `docs/api-reference.md` with title, intro, base URL assumption, and table of contents
- [x] 1.2 Document `POST /contracts/content` (purpose, auth/rate table, request body table, curl, response table, example JSON, errors)
- [x] 1.3 Document `POST /contracts/batch` (full section incl. enumerate_all + partial-failure behavior)
- [x] 1.4 Document `GET /contracts/types` (catalog listing endpoint)
- [x] 1.5 Document `GET /contracts/types/{contract_type}` (type metadata endpoint)
- [x] 1.6 Document `GET /tags/combinations/{contract_type}` (incl. filter_by_clause_coverage query param)
- [x] 1.7 Document `POST /tags/validate` (validation endpoint with valid/invalid examples)
- [x] 1.8 Document `GET /health` (public health check)

## 2. Schema Tables

- [x] 2.1 Add request schema tables: `ContractContentRequest`, `ContractBatchRequest`, `TagValidateRequest`
- [x] 2.2 Add response schema tables: `ContractContentResponse`, `ContractBatchResponse`, `ContractBatchItem`
- [x] 2.3 Add response schema tables: `ContractTypeCatalogResponse`, `ContractTypeCatalogItem`, `TypeMetadataResponse`, `ScenarioInfo`
- [x] 2.4 Add response schema tables: `TagCombinationsResponse`, `TagCombinationInfo`, `TagValidateResponse`
- [x] 2.5 Verify every table matches `api/schemas.py` field-for-field (name/type/required/default/description)

## 3. Error Catalog

- [x] 3.1 Document the standardized `ErrorResponse` shape with a field table
- [x] 3.2 Document 401 Unauthorized (trigger: auth enabled, X-API-Key missing) with example
- [x] 3.3 Document 403 Forbidden (trigger: invalid API key) with example
- [x] 3.4 Document 404 Not Found (trigger: unknown contract_type) with example
- [x] 3.5 Document 422 Unprocessable Entity (trigger: Pydantic validation failure) with example
- [x] 3.6 Document 429 Too Many Requests (trigger: rate limit exceeded) with example
- [x] 3.7 Document 500 Internal Server Error (trigger: unexpected exception) with example
- [x] 3.8 Cross-link each endpoint's "Errors" subsection to the catalog

## 4. Tag Vocabulary Reference (docs/tag-vocabulary.md)

- [x] 4.1 Create `docs/tag-vocabulary.md` with title and intro
- [x] 4.2 Document universal dimensions: source, stance, strength, risk, mandatory (with allowed values + zh labels)
- [x] 4.3 Document `sale` type-specific dims: risk_transfer_node, quality_objection_type, retention_of_title_status
- [x] 4.4 Document `lease` type-specific dims: priority_right_status, subletting_authorization_mode, accession_disposal_rule
- [x] 4.5 Document `employment` type-specific dims: special_restriction_period, working_hours_system
- [x] 4.6 Document seeded scenario vocabularies for high-variation types (sale, lease, employment, service, real_estate_lease)
- [x] 4.7 Add note that other types' dims/scenarios are queryable via `GET /tags/combinations/{type}`

## 5. Contract Type Catalog

- [x] 5.1 Add the full 43-type catalog table (key + zh_name) to docs/tag-vocabulary.md
- [x] 5.2 Cross-reference the contract_type field descriptions in api-reference.md to the catalog

## 6. Cross-linking & Navigation

- [x] 6.1 Add table of contents to api-reference.md linking to each endpoint + schema + error + tag section
- [x] 6.2 Add link from api-reference.md to docs/api-server.md (setup/config)
- [x] 6.3 Note live Swagger (/docs) and ReDoc (/redoc) availability in api-reference.md intro
- [x] 6.4 Add a one-line cross-link to docs/api-reference.md at the top of docs/api-server.md

## 7. Verification

- [x] 7.1 Confirm all 6 functional endpoints + health are documented
- [x] 7.2 Confirm every endpoint has a runnable curl example
- [x] 7.3 Confirm schema tables match api/schemas.py exactly
- [x] 7.4 Confirm error catalog covers 401/403/404/422/429/500
- [x] 7.5 Confirm 43 contract types are listed
- [x] 7.6 Update OpenSpec status after all docs complete
