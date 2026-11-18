## ADDED Requirements

### Requirement: Contract generation tools support true async execution

The system MUST provide native async implementations of contract generation APIs that do not block on thread-pooled sync functions.

#### Scenario: Async tool invocation via MCP
- **WHEN** a caller invokes an async MCP tool (e.g., `contract_content`, `tag_combinations_list`)
- **THEN** the tool returns a coroutine that resolves without invoking `anyio.to_thread.run_sync`

#### Scenario: Non-blocking DB queries
- **WHEN** an async tool needs to read clause data or tag vocabularies
- **THEN** it uses async database connections (asyncpg) with awaitable query methods

#### Scenario: LLM-bound operations parallelize correctly
- **WHEN** multiple LLM calls are needed (fill cache, evaluate) in a batch operation
- **THEN** they execute concurrently via `asyncio.gather` rather than sequentially


### Requirement: Batch contract generation capability

The system MUST allow generating multiple contracts simultaneously across different tag combinations.

#### Scenario: Explicit combination list
- **WHEN** caller provides `tag_combinations=[{"scenario": "农产品买卖", "stance": "pro_a"}, {"scenario": "消费品零售", "stance": "pro_b"}]` to `contract_generate_batch`
- **THEN** all contracts are generated in parallel and returned as a list ordered by input order

#### Scenario: Auto-enumerate valid combinations
- **WHEN** caller sets `enumerate_all=True` for a contract type
- **THEN** the system generates all tag combinations that have at least base clauses available

#### Scenario: Partial failure handling
- **WHEN** one contract in a batch fails (missing tags, coherence error)
- **THEN** subsequent contracts continue generating and results include error metadata per item


### Requirement: Content-first return model

The system MUST support returning contract content directly without requiring file I/O.

#### Scenario: Markdown-only response
- **WHEN** caller requests `format="markdown"` from `contract_content`
- **THEN** response includes `body_text` field with assembled markdown without DOCX/PDF generation

#### Scenario: JSON response with metadata
- **WHEN** caller requests `format="json"` 
- **THEN** response includes `{body_text, slots, instructions, law_refs, tags_used}` as structured JSON

#### Scenario: File output remains optional
- **WHEN** caller explicitly requests `format="pdf"` or `format="docx"`
- **THEN** system renders files to disk as before and includes paths in response


### Requirement: Tag enumeration API

The system MUST expose endpoints for enumerating valid tag combinations for any contract type.

#### Scenario: Base vocabulary listing
- **WHEN** caller invokes `tag_combinations_list(contract_type="sale")`
- **THEN** response includes universal dims (stance, strength, risk, mandatory) plus type-specific dims

#### Scenario: Scenario vocabulary exposure
- **WHEN** caller inspects response for a contract type with scenarios
- **THEN** each scenario entry shows `{name, has_tagged_clauses: bool, tagged_clause_count: int}`

#### Scenario: Combination count estimation
- **WHEN** caller queries a complex type (e.g., `sale` with 3 type-specific dims)
- **THEN** response includes `estimated_combinations` showing theoretical max combinations


---

## ADDED Requirements

### Requirement: Contract type catalog API

The system MUST expose comprehensive metadata about all contract types including clause coverage status.

#### Scenario: Type listing with stats
- **WHEN** caller invokes `contract_type_catalog()`
- **THEN** response includes sorted list with `{key, zh_name, slot_count, total_base_clauses, total_tagged_clauses, has_scenarios: bool}`

#### Scenario: Per-type scenario vocabulary
- **WHEN** caller requests `type_metadata(contract_type="lease")`
- **THEN** response includes `scenarios: [{name, clause_count, example_tags}]`

#### Scenario: Assembly readiness indicator
- **WHEN** caller inspects type metadata
- **THEN** response includes `assembly_ready: bool` which is `True` if type has >=1 assembly-ready custom clauses


---

## ADDED Requirements

### Requirement: Async fill/cache infrastructure

The system MUST support async slot filling with cache lookup for efficient repeated fills.

#### Scenario: Async fill service
- **WHEN** `fill_slots` is called in an async context
- **THEN** it makes non-blocking LLM requests and builds `filled_text` with populated placeholders

#### Scenario: Fill cache persistence
- **WHEN** same `(contract_type, scenario, slots, instructions)` tuple is requested twice
- **THEN** second call returns cached values via `fill_cache_id` without re-invoking LLM

#### Scenario: Temperature-controlled generation
- **WHEN** `temperature > 0` is passed to fill operation
- **THEN** filled values show appropriate variation (for creative drafting use cases)
