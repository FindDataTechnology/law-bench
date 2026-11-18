# legal-topic-tagging Specification

## Purpose

Register `legal_topic` as a type-specific tag dimension derived from rubric criteria, classify existing clauses to their primary legal topic via LLM, validate coverage completeness, and apply stance alias mapping for vocabulary consistency.

## Requirements

### Requirement: legal_topic tag dimension registration

The system MUST register `legal_topic` as a new type-specific tag dimension for each contract type.

#### Scenario: Register sale legal_topic dimension
- **WHEN** system calls `register_tag_dim("sale", "legal_topic", {ownership_transfer, risk_transfer, inspection_period, ...})`
- **THEN** `tag_vocab_list(contract_type="sale")` includes `"legal_topic": ["ownership_transfer", "risk_transfer", "inspection_period", "defect_warranty", "ownership_retention", "governing_law", "legal_citation", "clause_completeness", "party_identification", "legal_basis"]`

#### Scenario: Legal topic derivation from rubric criteria
- **WHEN** system creates legal_topic vocabulary for a contract type
- **THEN** each legal_topic value maps 1-to-1 to a rubric criterion name (e.g., rubric criterion `ownership_transfer` -> legal_topic `ownership_transfer`)

### Requirement: Clause legal_topic tagging via LLM classification

The system MUST assign exactly one primary `legal_topic` to each existing clause using LLM-based classification.

#### Scenario: Classify single clause
- **WHEN** system invokes LLM to classify a clause body against rubric criteria guidance
- **THEN** response is the single criterion name that the clause primarily addresses (e.g., "A clause about delivery risk transfer" -> `risk_transfer`)

#### Scenario: Batch backfill across all clauses
- **WHEN** system runs batch tagging on 1288 tagged clauses for `sale`
- **THEN** each clause's `tags.legal_topic` field is updated with its assigned topic

### Requirement: Coverage validation for legal_topics

The system MUST ensure every rubric criterion has at least one assembly-ready clause after backfill.

#### Scenario: Check coverage completeness
- **WHEN** system validates coverage for `sale`'s 10 rubric criteria
- **THEN** report shows each of the 10 legal_topics has >=1 assembly-ready clause OR reports gap

#### Scenario: Report missing topics
- **WHEN** a rubric criterion has 0 matching clauses
- **THEN** pipeline marks this as a "gap" that requires auto-generation in self-heal loop

### Requirement: Tag vocabulary listing with type-specific dims

The `tag_vocab_list` output schema SHALL drop the dead dimensions (`strength`, `risk`, `mandatory`) and MUST merge type-specific dims (including the new `legal_topic` axis, which replaces them as the filtering axis) into the response when a `contract_type` is given.

#### Scenario: Universal-only vocab query (unchanged)
- **WHEN** caller invokes `tag_vocab_list(contract_type=None)`
- **THEN** response includes only universal dims: `{source, stance}` (DELETED: strength, risk, mandatory)

#### Scenario: Type-specific vocab query (NEW)
- **WHEN** caller invokes `tag_vocab_list(contract_type="sale")`
- **THEN** response merges universal dims with type-specific dims:
  ```json
  {
    "stance": ["pro_a", "pro_b", "balanced"],
    "scenario": ["农产品买卖", "消费品零售", "工业品建材", "展销会", "共享服务", "其他"],
    "legal_topic": ["party_identification", "governing_law", "clause_completeness", "legal_citation", "ownership_transfer", "risk_transfer", "inspection_period", "defect_warranty", "ownership_retention", "legal_basis"],
    "retention_of_title_status": ["unregistered", "registered", "not_applicable"],
    "quality_objection_type": ["appearance_defect", "hidden_defect", "performance_failure"],
    "risk_transfer_node": ["on_delivery", "at_port_of_shipment", "at_destination", "delivered_to_carrier"]
  }
  ```
  (DELETED: `strength`, `risk`, `mandatory`)

#### Scenario: Lenient scenario handling (unchanged)
- **WHEN** caller passes an unknown scenario value to `tag_validate`
- **THEN** validation accepts it (scenario is free-form) rather than rejecting

### Requirement: Stance vocabulary aliasing

Tag validation and clause selection MUST apply an alias-mapping layer resolving `pro_seller` to `pro_a` and `pro_buyer` to `pro_b`, so pipeline-generated stance values match the DB vocabulary.

#### Scenario: Map pro_seller to pro_a
- **WHEN** system receives stance="pro_seller" from user input
- **THEN** internal representation resolves to `pro_a` (alias mapping applied)

#### Scenario: Map pro_buyer to pro_b
- **WHEN** system receives stance="pro_buyer" from user input
- **THEN** internal representation resolves to `pro_b` (alias mapping applied)

#### Scenario: Preserve pro_a/pro_b (no-op for aliases)
- **WHEN** system receives stance="pro_a" or "pro_b"
- **THEN** values pass through unchanged

#### Scenario: Custom clause filter resolves aliases
- **WHEN** system filters custom clauses by stance="pro_seller"
- **THEN** returns clauses with both `stance: pro_a` AND `stance: pro_seller` (backward compatibility)
