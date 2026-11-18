## ADDED Requirements

### Requirement: Comprehensive endpoint reference document

The system MUST provide a standalone Markdown document (`docs/api-reference.md`) documenting every HTTP endpoint with method, path, authentication requirement, rate-limit behavior, request schema, response schema, status codes, and at least one runnable curl example.

#### Scenario: Every functional endpoint documented
- **WHEN** a developer opens `docs/api-reference.md`
- **THEN** all 6 functional endpoints (`POST /contracts/content`, `POST /contracts/batch`, `GET /contracts/types`, `GET /contracts/types/{contract_type}`, `GET /tags/combinations/{contract_type}`, `POST /tags/validate`) plus `GET /health` are documented with method + path + purpose

#### Scenario: Each endpoint has a curl example
- **WHEN** a developer reads any endpoint section
- **THEN** the section includes a copy-pasteable `curl` command that runs against `http://localhost:8000` and produces the documented response

#### Scenario: Auth and rate-limit annotations per endpoint
- **WHEN** a developer reads an endpoint section
- **THEN** the section states whether the endpoint requires an API key, whether it's public, and its rate-limit tier (e.g. default vs batch stricter)


### Requirement: Schema tables match Pydantic models

The reference document MUST include field-by-field tables for every request and response Pydantic model, and each table MUST exactly match the corresponding model in `api/schemas.py` (field name, type, required/optional, default, description).

#### Scenario: All request models documented
- **WHEN** a developer looks up a request schema
- **THEN** they find a table for `ContractContentRequest`, `ContractBatchRequest`, `TagValidateRequest` listing every field with name/type/required/default/description

#### Scenario: All response models documented
- **WHEN** a developer looks up a response schema
- **THEN** they find tables for `ContractContentResponse`, `ContractBatchResponse` (+ `ContractBatchItem`), `ContractTypeCatalogResponse` (+ `ContractTypeCatalogItem`), `TypeMetadataResponse` (+ `ScenarioInfo`), `TagCombinationsResponse` (+ `TagCombinationInfo`), `TagValidateResponse`

#### Scenario: Nested models documented
- **WHEN** a response model references a nested model (e.g. `results: List[ContractBatchItem]`)
- **THEN** the nested model has its own table and is cross-referenced from the parent

#### Scenario: Field accuracy
- **WHEN** a reviewer diffs a schema table against its Pydantic source
- **THEN** every field name, type, required-flag, default, and description matches exactly


### Requirement: Error response catalog

The reference document MUST catalog every error status code the API can return, with the response body shape, an example, and the condition that triggers it.

#### Scenario: All error codes documented
- **WHEN** a developer reads the error catalog
- **THEN** it covers 401, 403, 404, 422, 429, and 500 with example JSON bodies

#### Scenario: Trigger condition per error
- **WHEN** a developer reads an error entry
- **THEN** the entry states the concrete condition (e.g. "401: API key auth enabled but `X-API-Key` header missing")

#### Scenario: Standardized error shape shown
- **WHEN** a developer reads the error catalog
- **THEN** the canonical `ErrorResponse` shape `{error, message, details, trace_id}` is documented with a field table


### Requirement: Tag vocabulary reference

The system MUST provide a `docs/tag-vocabulary.md` document listing the universal tag dimensions and representative type-specific dimensions so callers know valid tag values without querying the API.

#### Scenario: Universal dimensions documented
- **WHEN** a developer opens `docs/tag-vocabulary.md`
- **THEN** it lists `source`, `stance`, `strength`, `risk`, `mandatory` with their allowed values

#### Scenario: Type-specific dimension examples
- **WHEN** a developer reads the type-specific section
- **THEN** it documents at least `sale`, `lease`, and `employment` with their type-specific dims (e.g. sale: `risk_transfer_node`, `quality_objection_type`, `retention_of_title_status`) and allowed values

#### Scenario: Scenario vocabularies documented
- **WHEN** a developer looks up a contract type's scenarios
- **THEN** the document lists the seeded scenario values (e.g. sale: 农产品买卖, 消费品零售, 工业品建材, 展销会, 共享服务, 其他)


### Requirement: Contract type catalog in docs

The reference document MUST include the complete list of supported `contract_type` keys with their Chinese names, so callers know valid type values without a live query.

#### Scenario: Full type list
- **WHEN** a developer reads the contract type catalog section
- **THEN** all 43 contract types are listed with `key` and `zh_name` (e.g. `sale` / 买卖合同, `lease` / 租赁合同)

#### Scenario: Type list cross-referenced
- **WHEN** a developer reads the `contract_type` field description in any request schema
- **THEN** it points to the contract type catalog section for the valid value set


### Requirement: Cross-linking and navigation

The reference document MUST cross-link to the existing setup guide and the live Swagger UI, and provide a table of contents for navigation.

#### Scenario: Table of contents
- **WHEN** a developer opens `docs/api-reference.md`
- **THEN** a table of contents links to each endpoint section, the schema section, the error catalog, and the tag vocabulary

#### Scenario: Link to setup guide
- **WHEN** a developer needs to start the server
- **THEN** the reference links to `docs/api-server.md` for setup/configuration instructions

#### Scenario: Link to live Swagger
- **WHEN** a developer prefers interactive docs
- **THEN** the reference notes that Swagger UI is available at `/docs` and ReDoc at `/redoc` when the server is running
