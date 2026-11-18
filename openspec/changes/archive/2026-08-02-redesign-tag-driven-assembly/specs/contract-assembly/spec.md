## ADDED Requirements

### Requirement: Per-Section Override Resolution
The assembly engine SHALL resolve exactly one clause body per section for the assembled contract, chosen by precedence `custom(stance) > tagged(scenario) > base(母版)`. The base clause SHALL be the fallback for any section no override targets. The engine SHALL NOT concatenate multiple clause bodies within the same section.

#### Scenario: Override replaces base in a section
- **WHEN** a `tagged` clause and a `base` clause both target section `当事人` for the requested `scenario`
- **THEN** the assembled body for `当事人` contains only the `tagged` clause body, and the `base` clause body for that section is not present

#### Scenario: Custom overrides tagged and base
- **WHEN** `stance` is supplied and a `custom` clause (assembly-ready) targets the same section as a `tagged` clause and a `base` clause
- **THEN** the assembled body for that section contains only the `custom` clause body

#### Scenario: Base fallback for an untouched section
- **WHEN** no `tagged` or `custom` clause targets section `争议解决` for the requested tags
- **THEN** the assembled body for `争议解决` contains the `base` clause body

#### Scenario: No section ever contains more than one clause body
- **WHEN** the assembled body is produced for any combination of `scenario` and `stance`
- **THEN** every section heading in the body is followed by exactly one clause body (no concatenation of multiple clause bodies under a single heading)

### Requirement: Section Extension
The assembly engine SHALL include a `tagged` or `custom` clause whose `section` is absent from the 母版's canonical section set, inserting it as an extended section. Extended sections SHALL be placed after their nearest canonical predecessor and before `附则` and `签署信息`.

#### Scenario: Scenario extends a section the base lacks
- **WHEN** a `tagged` clause targets section `质量检验` (not in the 母版) for the requested `scenario`
- **THEN** the assembled body includes a `质量检验` section containing that clause body, positioned before `附则`

#### Scenario: No extension when section exists in base
- **WHEN** a `tagged` clause targets a section that exists in the 母版
- **THEN** that clause participates in override resolution for its section (it does not create an additional section)

### Requirement: Within-Source Variant Tiebreak
When a single source (`base`, `tagged`, or `custom`) has multiple clauses targeting the same section, the engine SHALL select one by: `manual=true` first, then the clause covering the most `{{slot}}`s, then the longest body, then the lowest `id`. This selection SHALL be reported in assembly diagnostics as heuristic-sourced.

#### Scenario: Heuristic picks the manual variant
- **WHEN** two `tagged` clauses target `合同标的` for the same scenario and one has `manual=true`
- **THEN** the `manual=true` clause body is used and the assembly diagnostic marks the section as heuristic-sourced

### Requirement: Slot Ontology and Normalization
The system SHALL maintain a slot ontology: a canonical core vocabulary (``REQUIRED_SLOTS``) shared across all types, plus a registry of high-frequency concepts (address, phone, agent, legal_rep, bank, account, delivery_date, etc.) each with a canonical name, a set of variant aliases (including role-prefix synonyms such as ``seller_address`` -> ``party_a_address``), and a slot instruction. Clause bodies and ``slot_instructions`` SHALL be normalized to canonical slot names at write/upsert time (``store._row``); ``body_hash`` SHALL be re-derived from the normalized body so dedup stays consistent. Clause-declared slots beyond the registry are permitted; every ``{{slot}}`` in the assembled body SHALL have a matching instruction (clause-declared, core default, or ontology fallback) - enforced by the coherence gate. The long tail of single-occurrence slots is intentionally not covered; an uninstructed singleton SHALL fail the gate as surfaced data debt.

#### Scenario: Non-canonical slot is normalized on write
- **WHEN** a clause body containing ``{{seller_name}}`` is upserted for a type whose canonical party slot is ``party_a``
- **THEN** the stored body uses ``{{party_a}}`` and the stored ``slot_instructions`` name ``party_a`` (not ``seller_name``)

#### Scenario: Role-prefixed variant is canonicalized per type
- **WHEN** a clause body containing ``{{lessor_address}}`` is upserted for ``lease``
- **THEN** the stored body uses ``{{party_a_address}}`` (lessor maps to party_a for lease)

#### Scenario: Ontology fallback instructs an uncovered body slot
- **WHEN** the assembled body contains ``{{party_a_bank}}`` and no clause declared an instruction for it
- **THEN** the ontology registry supplies an instruction for ``party_a_bank`` so the coherence gate passes

#### Scenario: Unknown singleton slot fails the gate
- **WHEN** the assembled body contains ``{{obscure_xyz}}`` for which no clause-declared, core, or ontology instruction exists
- **THEN** the coherence gate fails with an ``un-instructed slots`` diagnostic naming ``obscure_xyz``

### Requirement: Coherence Gate
Before rendering, the engine SHALL validate the resolved contract: (a) every canonical section of the 母版 is present or explicitly extended; (b) no duplicate section exists; (c) every `{{slot}}` in the assembled body has a matching slot instruction. A validation failure SHALL abort rendering and surface a diagnostic identifying the failing check.

#### Scenario: Missing slot instruction fails the gate
- **WHEN** the assembled body contains a `{{delivery_point}}` slot that has no entry in the assembled `instructions`
- **THEN** rendering is aborted and a diagnostic names `delivery_point` as the un-instructed slot

#### Scenario: Duplicate section fails the gate
- **WHEN** override resolution yields two clauses resolved to the same section (engine invariant violation)
- **THEN** rendering is aborted and a diagnostic names the duplicated section

#### Scenario: Coherent contract passes the gate
- **WHEN** every canonical section is present, no duplicates exist, and every slot is instructed
- **THEN** rendering proceeds and the deliverable is written

### Requirement: Scenario Override Curation Tooling
The system SHALL provide a diff-based curation process that, for a given corpus 示范文本 document and `contract_type`, retains only the sections whose body differs from the 母版's same section beyond a similarity threshold as `tagged` overrides, discards near-duplicate sections, and collapses multi-variant sections to a single best clause. The similarity threshold SHALL be a tunable parameter.

#### Scenario: Near-duplicate section is discarded
- **WHEN** a corpus doc's `当事人` section body is above the similarity threshold versus the 母版's `当事人`
- **THEN** no `tagged` clause is produced for `当事人` from that doc (the base clause covers it)

#### Scenario: Genuinely different section is kept as an override
- **WHEN** a corpus doc's `合同标的` section body is below the similarity threshold versus the 母版's `合同标的`
- **THEN** a `tagged` clause is produced for `合同标的` carrying `tags.scenario` derived from the doc, and at most one clause per section per scenario is emitted
