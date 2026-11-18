## ADDED Requirements

### Requirement: Unified Tag Storage
The system SHALL store ALL clause classification in the `tags` JSONB column. `tags.source ∈ {base, tagged, custom}` replaces the `category` column; `level` is derived (base=national, tagged=local, custom=null) and not stored; `region` is `tags.region` (already). The `clauses` table SHALL NOT have `category`, `level`, or `province` columns. A clause's classification is the union of its tag dimensions.

#### Scenario: source is a tag
- **WHEN** a base clause is stored
- **THEN** its `tags.source == "base"` and it has no `category`/`level` columns
#### Scenario: level derived from source
- **WHEN** a tagged clause has `tags.source == "tagged"`
- **THEN** its effective level is "local" (derived, not stored)
#### Scenario: no category column
- **WHEN** the schema is created
- **THEN** `clauses` has no `category`, `level`, or `province` column

### Requirement: Per-Type Tag Vocabulary
The system SHALL maintain a per-contract-type tag vocabulary in `tag_dims(contract_type, name, category, values, free_form, zh_label)` with PK `(contract_type, name)`. Universal dims (`source`, `region`, `stance`, `strength`, `risk`, `mandatory`) have `contract_type = NULL` (shared). Type-specific dims have `contract_type = <key>` (decoupled per type). `validate_tags(tags, contract_type)` SHALL accept dims that are universal OR belong to that `contract_type`, and reject others.

#### Scenario: universal dim shared
- **WHEN** `validate_tags({"stance": "pro_a"}, "employment")` is called
- **THEN** it accepts `stance` (universal, contract_type=NULL)
#### Scenario: type-specific dim decoupled
- **GIVEN** `tag_dims` has `(employment, special_restriction_period, ...)` and `(vam_agreement, vam_mechanism, ...)`
- **WHEN** `validate_tags({"special_restriction_period": "non_compete"}, "vam_agreement")` is called
- **THEN** it drops `special_restriction_period` (not in vam_agreement's vocab; it's employment-specific)
#### Scenario: same dim name, different type, separate rows
- **GIVEN** two types each define a dim named `priority_right_status` with different values
- **THEN** `tag_dims` has two rows (`(typeA, priority_right_status, ...)` and `(typeB, priority_right_status, ...)`) stored separately

### Requirement: Tag Categories
Each tag dim SHALL have a `category ∈ {来源, 利益倾向, 风险合规, 地域, 类型专属}`. The dashboard SHALL group dims by category; the assembly UI SHALL pick values per category.

#### Scenario: dims categorized
- **WHEN** tag_dims is read
- **THEN** `stance`/`strength` have category `利益倾向`; `risk`/`mandatory` have `风险合规`; `region` has `地域`; `source` has `来源`; type-specific have `类型专属`

### Requirement: Tag Governance (Reuse-or-Create)
`register_tag_dim(contract_type, name, category, values, free_form, zh_label)` SHALL reuse an existing dim (merge values, keep the row) if `(contract_type, name)` exists, else create a new row. The seeder, extraction, and manual dashboard entry SHALL all route dim creation through `register_tag_dim` so dims do not proliferate.

#### Scenario: reuse existing dim
- **GIVEN** `tag_dims` has `(employment, special_restriction_period, [probation, service_period])`
- **WHEN** `register_tag_dim("employment", "special_restriction_period", "类型专属", ["non_compete"])` is called
- **THEN** the row's values become `[probation, service_period, non_compete]` (merged, no new row)
#### Scenario: create new dim
- **WHEN** `register_tag_dim("employment", "new_dim_xyz", "类型专属", ["a"])` is called for a name not present
- **THEN** a new row `(employment, new_dim_xyz, ...)` is created

### Requirement: Auto-Tag at Extraction
The extraction LLM SHALL suggest `stance`/`strength`/`risk`/`mandatory` per clause; `source` SHALL be set from the doc's level (base/tagged); `region` from the inferred province. All auto-suggested/set tags SHALL enter `tag_review` as `pending`. Type-specific dims SHALL NOT be auto-suggested (set manually).

#### Scenario: extraction auto-tags universal dims
- **WHEN** a provincial 示范文本 is extracted
- **THEN** each clause's `tags` includes `source="tagged"`, `region=<province>`, and LLM-suggested `stance`/`strength`/`risk`/`mandatory`; `tag_review` has each of those dims as `pending`
#### Scenario: type-specific not auto-tagged
- **WHEN** an employment clause is extracted
- **THEN** `tags` does NOT include `special_restriction_period` (left for manual entry)

### Requirement: Tag Review (Per-Dim + Bulk)
The system SHALL store per-dim review status in `clauses.tag_review` JSONB `{dim: pending|approved|rejected}`. A clause is "assembly-ready" when every dim in its `tags` has `tag_review[dim] == "approved"`. The dashboard SHALL support per-dim approve/reject AND bulk-approve-all (set every set dim to approved).

#### Scenario: per-dim review
- **GIVEN** a clause with `tags={stance:pro_a, strength:strong}` and `tag_review={stance:pending, strength:pending}`
- **WHEN** the operator approves `stance` only
- **THEN** `tag_review.stance="approved"`, `tag_review.strength="pending"`, and the clause is NOT assembly-ready (strength still pending)
#### Scenario: bulk approve
- **WHEN** the operator bulk-approves the clause
- **THEN** all set dims become `approved` and the clause is assembly-ready
#### Scenario: list by review status
- **WHEN** `list_clauses(..., review_status="pending")` is called
- **THEN** only clauses with at least one pending dim are returned

### Requirement: Assembly by Tags (Custom Review-Gated)
`generate_contract_assembled(contract_type, tags={...})` SHALL select base clauses (`tags.source=base`), tagged clauses (`tags.source=tagged ∧ tags.region=<tags.region>`), and custom clauses (`tags.source=custom` matching the supplied `tags` AND assembly-ready). base/tagged SHALL NOT be review-gated; only custom SHALL require all set dims approved. An unknown `contract_type` SHALL raise `NotFoundError`.

#### Scenario: assemble by stance, only approved custom
- **GIVEN** two custom clauses with `stance=pro_a`, one `assembly-ready` and one with a pending dim
- **WHEN** `generate_contract_assembled("sale", tags={"source":"custom","stance":"pro_a"})` is called
- **THEN** only the assembly-ready custom clause is included (plus base + tagged)
#### Scenario: base/tagged not review-gated
- **GIVEN** a base clause with a pending `tag_review`
- **WHEN** assembly runs
- **THEN** the base clause is still included (backbone, not gated)
#### Scenario: unknown type raises
- **WHEN** `generate_contract_assembled("does_not_exist", tags={...})` is called
- **THEN** `NotFoundError` is raised
