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

---

## REMOVED Requirements

### Requirement: Dead dimension filtering in tag_combinations

**REASON**: `strength`, `risk`, `mandatory` dimensions are removed entirely from consideration.

**Migration**: Users should filter combinations by remaining meaningful dimensions (`stance`, `scenario`, `legal_topic`).

#### Scenario: Old dimension ignored
- **WHEN** a prior integration passed `tags={stance: "balanced", strength: "strong"}`
- **THEN** `strength` is silently dropped with no error (backward compatible deletion)

### Requirement: Combinatorial enumeration using all dims

**REASON**: Enumerating all permutations including dead dimensions wastes computation.

**Reason**: Previous implementation included `{source, stance, strength, risk, mandatory}` in the Cartesian product.

**Migration**: Callers should use `include_legal_topic=true` opt-in for type-specific dimensions.

#### Scenario: New minimal enumeration
- **WHEN** system computes combinations with default parameters
- **THEN** only `{source, stance}` universal dims + type-specific dims (`scenario`, `legal_topic`) are enumerated
