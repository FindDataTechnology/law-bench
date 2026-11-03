## ADDED Requirements

### Requirement: Direct contract content retrieval

The system MUST return assembled contract markdown text without requiring DOCX/PDF generation.

#### Scenario: Content-only response
- **WHEN** caller invokes `contract_content(contract_type="sale", tags={"stance": "balanced"})`
- **THEN** response is `{body_text: string, slots: [...], instructions: [...], law_refs: [...]}` within <50ms (no file I/O)

#### Scenario: Assemble model applied correctly
- **WHEN** caller provides both `scenario` and `stance` tags
- **THEN** returned body_text reflects correct override hierarchy: custom(stance) > tagged(scenario) > base fallback

#### Scenario: Coherence validation before return
- **WHEN** assembled contract fails coherence gate (missing required slots)
- **THEN** API returns error with `coherence_errors: [list of violations]`


### Requirement: Slot instruction mapping

The system MUST expose slot instructions alongside contract body for form-filling UIs.

#### Scenario: Canonical slot extraction
- **WHEN** caller receives contract content
- **THEN** response includes all 12 canonical slots plus any section-specific slots from body

#### Scenario: Instruction metadata completeness
- **WHEN** caller inspects a slot instruction in response
- **THEN** it includes `{name, label, description, example, required}` fields

#### Scenario: Ontology-backed defaults
- **WHEN** body contains slot but no declared instruction
- **THEN** system falls back to slot ontology (`instruction_for_slot`) to provide default instruction


### Requirement: Law reference aggregation

The system MUST aggregate and deduplicate law references across resolved clauses.

#### Scenario: Law ref extraction from body
- **WHEN** assembled contract contains provisions like《中华人民共和国民法典》合同编
- **THEN** these are extracted into `law_refs` list with `{name, category, url_reference}`

#### Scenario: Category-sorted output
- **WHEN** caller receives law_refs
- **THEN** they are sorted by predefined category order (statute > regulation > judicial interpretation > other)

#### Scenario: Deduplication guarantee
- **WHEN** multiple clauses reference same law
- **THEN** response shows each unique law only once


---

## ADDED Requirements

### Requirement: Batch response format standardization

The system MUST return consistent structured responses for batch operations.

#### Scenario: Uniform error structure
- **WHEN** a batch item fails
- **THEN** response includes `{success: false, error: {code, message, details}}` object

#### Scenario: Partial success indication
- **WHEN** batch has mix of successes and failures
- **THEN** top-level response includes `{success_count, failure_count, total_requested}` summary

#### Scenario: Per-item provenance
- **WHEN** caller inspects failed batch item
- **THEN** response shows which tag combination caused failure (`requested_tags: {...}`)


---

## ADDED Requirements

### Requirement: Type catalog performance

The system MUST serve type catalog queries efficiently via caching.

#### Scenario: Cached enumeration
- **WHEN** caller requests contract type list
- **THEN** response served from memory cache (lru_cache on registry) with no DB round-trip

#### Scenario: Clause count freshness
- **WHEN** system is restarted after new clause insertions
- **THEN** next catalog query reflects updated counts (re-computes on demand or invalidates cache)
