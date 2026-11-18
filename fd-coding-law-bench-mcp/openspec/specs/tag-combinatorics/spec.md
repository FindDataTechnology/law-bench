## ADDED Requirements

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


### Requirement: Valid combination enumeration

The system MUST enumerate all valid tag combinations by Cartesian product of allowed values.

#### Scenario: Cartesian product generation
- **WHEN** caller requests combinations for a contract type with 3 dim1={a,b}, 2 dim2={x,y,z}
- **THEN** response lists 6 combinations: `[{dim1:a,dim2:x}, {dim1:a,dim2:y}, ..., {dim1:b,dim2:z}]`

#### Scenario: Stance-scenario independence
- **WHEN** caller inspects generated combinations
- **THEN** every stance value pairs with every scenario value (no hard-coded exclusions)

#### Scenario: Combinatorial explosion prevention
- **WHEN** estimated combinations exceed 1000
- **THEN** response includes warning flag `combinatorial_warning: true` suggesting filtered enumeration


### Requirement: Clause availability metadata

The system MUST report which combinations have backing clauses (tagged/custom).

#### Scenario: Base clause coverage check
- **WHEN** caller inspects a scenario entry in `tag_combinations_list`
- **THEN** response shows `base_clauses_present: true` if that section has base fallback

#### Scenario: Tagged clause presence indicator
- **WHEN** caller queries `lease` contract with scenario "土地经营权流转"
- **THEN** response shows `has_tagged_clauses: true` and `clause_ids: [7094, 7095, ...]`

#### Scenario: Custom clause stance matching
- **WHEN** caller filters combinations by `stance="pro_a"`
- **THEN** only scenarios with assembly-ready pro_a custom clauses are marked available


### Requirement: Scenario-based filtering

The system MUST support filtering tag combinations by scenario presence.

#### Scenario: Show only populated scenarios
- **WHEN** caller sets `filter_by_clause_coverage=true`
- **THEN** response excludes scenarios with no tagged clauses

#### Scenario: Fallback scenario identification
- **WHEN** caller inspects a contract type's scenarios
- **THEN** response marks `其他` (other/fallback) scenarios explicitly

---

## ADDED Requirements

### Requirement: Cross-type scenario comparison

The system MUST enable comparing scenarios across multiple contract types.

#### Scenario: Unified scenario list
- **WHEN** caller invokes `compare_scenarios(types=["sale", "work", "service"])`
- **THEN** response shows shared vs unique scenarios (e.g., both have "装饰装修" variants)

#### Scenario: Coverage gap identification
- **WHEN** caller inspects comparison output
- **THEN** response highlights types missing scenario coverage that others have

---

## ADDED Requirements

### Requirement: Clean combinatorial space (delete dead dims)

The system MUST exclude dead tag dimensions from `tag_combinations_list` output.

#### Scenario: Enumerate sale combinations without dead dims
- **WHEN** system calls `tag_combinations_list(contract_type="sale", include_clause_availability=true)`
- **THEN** response excludes combinations built from `{strength, risk, mandatory}`; only includes `{stance, scenario, legal_topic, retention_of_title_status, quality_objection_type, risk_transfer_node}`

#### Scenario: Combinatorial explosion prevention
- **WHEN** estimated tagged clause combinations exceed 1000
- **THEN** response includes warning flag `combinatorial_warning: true` suggesting filtered enumeration by stance/scenario

### Requirement: legal_topic in combination enumeration

The system MUST include `legal_topic` as a dimension for contract types with rubrics.

#### Scenario: Generate legal_topic values per topic
- **WHEN** system enumerates combinations for sale
- **THEN** each of the 10 legal_topics appears as an independent value in the Cartesian product

#### Scenario: Filter by legal_topic presence
- **WHEN** caller requests combinations where `has_tagged_clauses=true` AND `legal_topic="ownership_transfer"`
- **THEN** response returns only scenarios where ownership_transfer has assembly-ready clauses

---

## MODIFIED Requirements

### Requirement: Clause selection precedence with legal_topic

`_select_clauses` MUST prioritize clauses matching the target `legal_topic` when available (selection is by section AND topic coverage), and SHALL fall back to section-only selection (old behavior) when no topic-matching clause exists.

#### Scenario: Override resolution adds legal_topic filter
- **WHEN** resolving one clause per section
- **THEN** precedence is `custom(stance+legal_topic) > tagged(scenario+legal_topic) > base(母版)`

#### Scenario: Coverage-based fallback
- **WHEN** no custom clause exists for a legal_topic
- **THEN** pipeline falls back to any clause covering that section (old behavior)

#### Scenario: Tag alias resolution during clause selection
- **WHEN** filtering custom clauses by stance
- **THEN** alias mapping is applied: clauses with `stance: pro_seller` match user request for `pro_a`
