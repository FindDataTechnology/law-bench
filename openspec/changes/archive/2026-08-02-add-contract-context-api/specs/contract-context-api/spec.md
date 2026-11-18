## ADDED Requirements

### Requirement: Contract Class List Endpoint
The system SHALL expose `GET /api/contracts` returning the supported contract classes as a JSON list of `{key, zh}` objects in `contract_types.json` file order. It SHALL be documented in the `/api/docs` OpenAPI schema.

#### Scenario: List contract classes
- **WHEN** `GET /api/contracts` is called
- **THEN** it returns a 200 with a JSON array of 43 entries, each `{key, zh}` (e.g. `{"key": "sale", "zh": "买卖合同"}`)

### Requirement: Comprehensive Context Bundle Endpoint
The system SHALL expose `GET /api/contracts/{contract_type}` returning a JSON bundle for one contract class containing: `type`, `zh_name`, `template` (`{body, slots}`), `slot_instructions` (the manifest, each entry `{name, label, description, example, required, source}`), `laws` (`{refs: [{name, category, category_zh, sources}]}` - structured refs only, no survey markdown), `tags` (the merged vocabulary `{dim: [values]}` for the type), `sections` (the canonical `SECTION_ORDER` list), `clauses` (a summary `{base: N, tagged: N, custom: N}`), `rubric` (`{name}` of the latest-version rubric for the type, or `null`), and `prompts` (`[{name, purpose}]` for the type). It SHALL return 404 for an unknown contract type. It SHALL be documented in `/api/docs`.

#### Scenario: Fetch the comprehensive bundle for a type
- **WHEN** `GET /api/contracts/sale` is called
- **THEN** it returns 200 with an object whose `type` is `"sale"`, `template.body` is non-empty Markdown, `template.slots` is the de-duplicated slot names, `slot_instructions` is non-empty, `laws.refs` is a list of cited laws, `tags` has a non-empty `stance` list, `sections` lists `"当事人"` first, `clauses` has integer `base`/`tagged`/`custom` counts, and `rubric.name` matches `contract_sale_v<latest>`

#### Scenario: Unknown contract type returns 404
- **WHEN** `GET /api/contracts/does_not_exist` is called
- **THEN** it returns 404 with an `{"error": ...}` body

### Requirement: Slot API Endpoint with Ontology Coverage
The system SHALL expose `GET /api/contracts/{contract_type}/slots` returning the slot-instruction manifest for the type as a JSON list of `{name, label, description, example, required, source}`. The list SHALL cover every `{{slot}}` in the template body. For slots not in the type's manifest, the instruction SHALL be resolved from `slot_ontology.instruction_for_slot(name)` with `source: "ontology"`; slots present in the manifest SHALL have `source: "registry"`; template slots with no instruction anywhere SHALL appear with `source: "uncovered"` and empty guidance fields. It SHALL return 404 for an unknown contract type. It SHALL be documented in `/api/docs`.

#### Scenario: Slot manifest covers template slots
- **WHEN** `GET /api/contracts/sale/slots` is called
- **THEN** it returns 200 with a list whose `name` set equals `GET /api/contracts/sale`'s `template.slots`, and every entry has a non-empty `label` and `required` boolean

#### Scenario: Variant slot resolved via ontology
- **WHEN** a type's template body contains `{{seller_address}}` and the manifest has no `seller_address` entry
- **THEN** `GET /api/contracts/{type}/slots` includes an entry with `name: "seller_address"`, `source: "ontology"`, and a non-empty `label`/`description` derived from the `address` concept

#### Scenario: Unknown contract type returns 404
- **WHEN** `GET /api/contracts/does_not_exist/slots` is called
- **THEN** it returns 404

### Requirement: Per-Type Laws Endpoint
The system SHALL expose `GET /api/contracts/{contract_type}/laws` returning `{refs, survey_md}` where `refs` is the structured list `[{name, category, category_zh, sources}]` (reusing `extract_laws_for_type`) and `survey_md` is `{doubao, deepseek}` with each value the full survey markdown string or `null` when absent (reusing `get_law_info`). It SHALL return 404 for an unknown contract type. It SHALL be documented in `/api/docs`.

#### Scenario: Fetch laws for a type
- **WHEN** `GET /api/contracts/sale/laws` is called
- **THEN** it returns 200 with `refs` a non-empty list whose entries each have a `name`, a `category` in `CATEGORY_ORDER`, and a `sources` list, and `survey_md.doubao` is a non-empty Markdown string

#### Scenario: Unknown contract type returns 404
- **WHEN** `GET /api/contracts/does_not_exist/laws` is called
- **THEN** it returns 404

### Requirement: Per-Type Tag Vocabulary Endpoint
The system SHALL expose `GET /api/contracts/{contract_type}/tags` returning the merged tag vocabulary for the type as `{dim: [allowed values]}`, combining universal dims (`source`, `stance`, `strength`, `risk`, `mandatory`) with the type-specific dims from the `tag_dims` table (e.g. `scenario`, type-specific controlled dims). It SHALL return 404 for an unknown contract type. It SHALL be documented in `/api/docs`.

#### Scenario: Fetch tags for a type
- **WHEN** `GET /api/contracts/sale/tags` is called
- **THEN** it returns 200 with an object whose `stance` is `["pro_a","pro_b","balanced"]` and which includes a `scenario` key with a non-empty value list

#### Scenario: Unknown contract type returns 404
- **WHEN** `GET /api/contracts/does_not_exist/tags` is called
- **THEN** it returns 404

### Requirement: Clause Catalog Endpoint with Filters and Pagination
The system SHALL expose `GET /api/contracts/{contract_type}/clauses` returning a paginated JSON list of clauses for the type, each clause `{id, section, source, manual, tags, body}` (or the existing `list_clauses` row shape). It SHALL accept query parameters `scenario`, `stance`, `source` (each optional, filtering the corresponding tag/source), and `limit` (default 50, max 200) / `offset` (default 0) for pagination. The response SHALL include a `total` count of matching clauses. It SHALL return 404 for an unknown contract type. It SHALL be documented in `/api/docs`.

#### Scenario: List clauses for a type with defaults
- **WHEN** `GET /api/contracts/sale/clauses` is called
- **THEN** it returns 200 with a list of at most 50 clauses, each having `id`, `section`, `source`, and `body`, plus a `total` integer >= the returned count

#### Scenario: Filter clauses by scenario and stance
- **WHEN** `GET /api/contracts/sale/clauses?scenario=农产品买卖&stance=pro_a` is called
- **THEN** every returned clause's `tags.scenario` is `"农产品买卖"` and `tags.stance` is `"pro_a"`

#### Scenario: Pagination limits the page size
- **WHEN** `GET /api/contracts/sale/clauses?limit=10&offset=0` is called
- **THEN** it returns at most 10 clauses and a `total` reflecting the full match count

#### Scenario: Unknown contract type returns 404
- **WHEN** `GET /api/contracts/does_not_exist/clauses` is called
- **THEN** it returns 404

### Requirement: Contract Generation Endpoint
The system SHALL expose `POST /api/contracts/{contract_type}/generate` accepting a JSON body `{scenario?, stance?, custom_clause_ids?, format}` where `format` is `"docx"` (default), `"pdf"`, `"both"`, or `"markdown"`. It SHALL assemble the contract via `generate_contract_assembled` (per-section override `custom > tagged > base` + coherence gate) and return `{body_text, slots, instructions, law_refs, diagnostics, docx_url?, pdf_url?}` where `body_text` is always present. For `format: "markdown"` no file is written and `docx_url`/`pdf_url` are `null`. For `docx`/`pdf`/`both` the file(s) SHALL be written under `output/contracts/` and the corresponding URL(s) returned. A coherence-gate failure (`CoherenceError`) SHALL produce 422 with a diagnostic `{"error": ...}` naming the failing check(s). An unknown contract type SHALL produce 404. It SHALL be documented in `/api/docs`.

#### Scenario: Generate docx (default)
- **WHEN** `POST /api/contracts/sale/generate` is called with no `format` (or `{"format": "docx"}`)
- **THEN** it returns 200 with a non-empty `body_text`, a `slots` list, `instructions`, `law_refs`, `diagnostics`, and `docx_url` a non-null URL string, `pdf_url` `null`

#### Scenario: Generate with tags
- **WHEN** `POST /api/contracts/sale/generate` is called with `{"scenario": "农产品买卖", "stance": "pro_a"}`
- **THEN** it returns 200 and the assembled `body_text` reflects the scenario-tagged clause overrides for that scenario

#### Scenario: Generate markdown returns text only
- **WHEN** `POST /api/contracts/sale/generate` is called with `{"format": "markdown"}`
- **THEN** it returns 200 with a non-empty `body_text` and `docx_url`/`pdf_url` both `null` (no file written)

#### Scenario: Coherence failure returns 422
- **WHEN** `POST /api/contracts/{type}/generate` is called with a clause selection that drops a canonical base section
- **THEN** it returns 422 with an `{"error": ...}` body naming the missing section

#### Scenario: Unknown contract type returns 404
- **WHEN** `POST /api/contracts/does_not_exist/generate` is called
- **THEN** it returns 404

### Requirement: Router Wiring and Schema Inclusion
The system SHALL include the `contract-context` router in `src/web/app.py` so that all endpoints above appear in the `/api/docs` OpenAPI schema (i.e. none use `include_in_schema=False`). DB-backed endpoints SHALL take `db: Path = Depends(get_db)` reusing the existing dependency. `NotFound` errors from the service layer SHALL map to 404 via the existing exception handlers.

#### Scenario: Endments appear in the OpenAPI schema
- **WHEN** `GET /openapi.json` is fetched
- **THEN** the paths include `/api/contracts`, `/api/contracts/{contract_type}`, `/api/contracts/{contract_type}/slots`, `/api/contracts/{contract_type}/laws`, `/api/contracts/{contract_type}/tags`, `/api/contracts/{contract_type}/clauses`, and `POST /api/contracts/{contract_type}/generate`

#### Scenario: Unknown type maps to 404 via existing handler
- **WHEN** any contract-context endpoint is called with an unknown `{contract_type}`
- **THEN** the response is 404 with an `{"error": ...}` body (routed through the registered `NotFoundError` handler)
