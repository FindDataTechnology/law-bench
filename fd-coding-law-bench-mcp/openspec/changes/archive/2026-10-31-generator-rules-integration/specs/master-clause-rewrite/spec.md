## ADDED Requirements

### Requirement: Required-element-driven 母版 completeness

For each Category A contract type (the ~24 types that overlap with the generator's type tree), the system MUST ensure its base (母版) clause set covers every element the generator marks `required: true` for that type's inheritance chain. A required element with no corresponding base clause triggers a merge of the generator's clause for that element/topic into the base set; an existing richer base clause on the same topic is NOT replaced.

#### Scenario: Missing required-element clause is merged
- **WHEN** the importer runs for `lease` and the generator's `elements_for("lease")` includes a required element `租金金额` whose topic (`rent`) has no base clause covering it
- **THEN** the generator's rent clause body is added as a new base clause for `lease`
- **AND** its `source` is set from the generator's `source` (e.g. 民法典§721)

#### Scenario: Existing richer base is preserved
- **WHEN** the importer runs for `sale` and the generator offers a `sale.object` clause ("出卖人将{{标的物名称}}…") but law-bench's sale base already has a richer 标的物 clause with inspection-period and ownership-retention detail
- **THEN** the existing base clause body is left unchanged
- **AND** only the `source`/`law_ref` citation may be augmented, never the body

#### Scenario: Sub-type leaf becomes a tagged clause
- **WHEN** the importer encounters `lease.immovable.house` (a param-door leaf) clauses
- **THEN** they are stored as `tagged` clauses with `scenario="房屋租赁"` (mapped to `real_estate_lease`), not as base
- **AND** the existing scenario-filtered assembly consumes them without code change

### Requirement: Category B new-type seeding

For each of the ~23 generator-only contract types (no law-bench `contract_type` row), the system MUST create a `contract_type` row and seed its base clauses from the generator's `clauses/<type>.yaml`, with `{{slot}}` placeholders and `source`/`law_ref` preserved.

#### Scenario: New type created with seeded base
- **WHEN** the importer runs for `will` (遗嘱, a Category B type)
- **THEN** a `contract_type` row `will` is created
- **AND** base clauses from `clauses/will.yaml` are inserted with `source="base"`
- **AND** each clause's `{{slot}}` placeholders become `slot_instructions` entries with `required` matching the generator's `elements[].required`

#### Scenario: New type is draftable but unscored
- **WHEN** a Category B type has been seeded
- **THEN** `contract_generate` can assemble a draft from its base clauses
- **AND** no rubric exists for it yet (rubric authoring is explicitly out of scope for this change)

### Requirement: Idempotent import with merge-not-replace

The importer MUST be re-runnable without overwriting manual edits. Existing base/tagged clauses matched by `body_hash` + `contract_type` + `section` are skipped, not replaced. A `imported_at` timestamp and `source_hash` are recorded per imported row so drift from the generator's YAML is detectable on re-run.

#### Scenario: Re-run skips edited clauses
- **WHEN** the importer is run a second time after a human edited a clause body via `clause_update`
- **THEN** the edited clause is not overwritten
- **AND** only previously-absent clauses are inserted

#### Scenario: Stale YAML detected
- **WHEN** the importer re-runs and a generator `validation/*.yaml` file's hash differs from the stored `source_hash`
- **THEN** the drift is logged (new/changed constraints listed) without silent overwrites
