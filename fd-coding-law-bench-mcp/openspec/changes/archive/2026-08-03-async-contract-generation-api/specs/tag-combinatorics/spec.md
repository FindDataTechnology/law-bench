## ADDED Requirements

### Requirement: Tag vocabulary listing with type-specific dims

The system MUST expose `tag_vocab_list` with support for both universal and per-type dimensions.

#### Scenario: Universal-only vocab query
- **WHEN** caller invokes `tag_vocab_list(contract_type=None)`
- **THEN** response includes only universal dims: `{source, stance, strength, risk, mandatory}`

#### Scenario: Type-specific vocab query
- **WHEN** caller invokes `tag_vocab_list(contract_type="sale")`
- **THEN** response merges universal dims with type-specific dims: `{risk_transfer_node, quality_objection_type, retention_of_title_status}`

#### Scenario: Lenient scenario handling
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
