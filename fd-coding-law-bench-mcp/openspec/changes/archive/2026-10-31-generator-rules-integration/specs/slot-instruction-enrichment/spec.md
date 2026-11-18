## ADDED Requirements

### Requirement: Slot instructions carry prompt and type

Each `slot_instructions` entry (jsonb on clauses) MAY carry two optional keys: `prompt` (the generator's 大白话问法 plain-language question) and `type` (`text|money|date|duration|enum`). An `enum`-typed slot MUST carry `enum_values` (the allowed values). These keys are additive — existing slots without them continue to function; no DDL is required.

#### Scenario: Money slot enriched
- **WHEN** the importer enriches a `租金金额` slot from the generator's element `{id:租金金额, type:money, prompt:"每个月租金是多少钱？"}`
- **THEN** the slot_instructions entry gains `"prompt":"每个月租金是多少钱？"` and `"type":"money"`
- **AND** the existing name/label/example/required/description keys are unchanged

#### Scenario: Enum slot carries allowed values
- **WHEN** a generator element has `type: enum{现金,转账,支票}` (payment method)
- **THEN** the slot_instructions entry gains `"type":"enum"` and `"enum_values":["现金","转账","支票"]`

### Requirement: Required elements map to required slots

A generator element marked `required: true` MUST map to a slot with `required: true`. This drives the 母版 skeleton: required slots render `【待确认：key】` when absent but never block assembly (soft-fill), while defining which clauses the 母版 must contain.

#### Scenario: Required element becomes required slot
- **WHEN** the generator's `甲方名称` element has `required: true`
- **THEN** the corresponding slot_instructions entry has `"required":true`

### Requirement: Field-level inheritance via per-type override

The generator's field-level merge (a deeper type level redefines one field of a root element, e.g. loan redefines root `甲方(出租方)名称` → `甲方(出借人)名称` while inheriting `required`/`type`) MUST be represented as a per-type slot override: the slot `name` (key) stays constant so `{{party_a}}` works across types, but `label`/`prompt` differ per `contract_type`.

#### Scenario: Loan redefines party label
- **WHEN** the importer enriches slots for `loan`
- **THEN** the `party_a` slot retains `name:"party_a"` and `required:true` (inherited from root)
- **AND** its `label`/`prompt` reflect "出借人" rather than "出租方"

### Requirement: Re-derivation round-trips new keys

`clause_update` and `create_clause` MUST round-trip the `prompt`, `type`, and `enum_values` keys when re-deriving `slot_instructions` from a clause body. Editing a clause body that introduces a new `{{slot}}` derives a slot entry with the new keys where known (prompt/type from a generator element match, else omitted); existing enriched keys on unchanged slots are preserved.

#### Scenario: Update preserves enrichment
- **WHEN** a clause body is edited via `clause_update` and a slot already carries `prompt`/`type`
- **THEN** the re-derived slot_instructions retains those keys for slots whose body text is unchanged
- **AND** newly-introduced slots are derived with whatever generator element match exists, or left without prompt/type
