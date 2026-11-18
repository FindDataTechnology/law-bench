# Generation Prompts Specification

## Purpose
Storage and management of per-contract-type generation/drafting prompts.
## Requirements
### Requirement: Generation Prompt Storage
The system SHALL store generation prompts in a `prompts` table within the PostgreSQL database addressed by the `database_url` environment variable. Each prompt SHALL have a unique `name`, a `contract_type` (e.g. `sale`), a `purpose` (e.g. `drafting`), a `content` body (the prompt text), a `source`, an optional `description`, and a `created_at` timestamp. The `prompts` table SHALL be created by the same schema source of truth that creates `rubrics` and `criteria` (`scripts/extract_harbor_rules.py`'s `SCHEMA`), so any seeder that calls `create_schema()` establishes it.

#### Scenario: A prompt is stored with its fields
- **WHEN** a generation prompt is inserted with name `draft_sale`, contract_type `sale`, purpose `drafting`, content body, and `source = local`
- **THEN** a single row is stored in `prompts` with all fields populated and a `created_at` timestamp
- **AND** the `prompts` table exists in the same database as `rubrics` and `criteria`

#### Scenario: Prompt names are unique
- **WHEN** a prompt is inserted whose `name` already exists in `prompts`
- **THEN** the insertion is rejected with a clear conflict error
- **AND** no duplicate row is created

### Requirement: Idempotent Prompt Seeding
The system SHALL provide `scripts/seed_contract_prompts.py` that idempotently upserts a registry of per-contract-type drafting prompts (one per 民法典 named contract type) into the `prompts` table. Re-running the script SHALL NOT create duplicate prompt rows and SHALL NOT modify any row in `rubrics` or `criteria`.

#### Scenario: Seeding prompts is idempotent
- **WHEN** `seed_contract_prompts.py` is run a second time
- **THEN** the `prompts` row count is unchanged
- **AND** no duplicate prompt rows are created
- **AND** the `rubrics` and `criteria` row counts are unchanged

#### Scenario: Seeding does not touch rubrics
- **WHEN** `seed_contract_prompts.py` runs after `seed_contract_rubrics.py` has populated the 19 per-class rubrics
- **THEN** no rubric or criterion row is modified or deleted

### Requirement: Prompt Provenance
Generation prompts SHALL always have `source = local`. They are authored content, not extracted from an upstream package, and SHALL NOT be subject to any harbor re-extraction. Harbor extraction SHALL NOT read or modify the `prompts` table.

#### Scenario: Harbor re-extraction leaves prompts untouched
- **WHEN** the harbor extraction script runs after prompts have been seeded
- **THEN** every row in `prompts` remains unchanged
- **AND** no prompt row is added, modified, or deleted by extraction

### Requirement: Prompt Query
The system SHALL support listing all prompts (with name, contract_type, purpose, and source) and fetching a single prompt by `name`, returning its full content. This enables both the management UI and future crew runtime consumption.

#### Scenario: List all prompts
- **WHEN** a caller lists prompts
- **THEN** every prompt row is returned with its name, contract_type, purpose, and source

#### Scenario: Fetch a prompt by name
- **WHEN** a caller requests a prompt by its `name`
- **THEN** the prompt's name, contract_type, purpose, content, source, description, and created_at are returned
- **AND** an unknown name raises a clear not-found error

### Requirement: Prompt Type (Variant Lineage)
A generation prompt SHALL carry a `prompt_type` field: a free-string variant/lineage tag (e.g. `baseline`, `experimental`, `improved`, `reverted`, `v2-strict`) identifying where the prompt sits in its iteration lineage. The field SHALL be stored in the `prompts` table (added to the schema source of truth in `scripts/extract_harbor_rules.py`'s `SCHEMA`), SHALL be optional (nullable/blank), and SHALL be surfaced in prompt CRUD. The 19 seeded per-type prompts SHALL be seeded with `prompt_type = baseline`.

#### Scenario: A prompt is stored with its type
- **WHEN** a prompt is created with name `draft_sale_v2`, contract_type `sale`, purpose `drafting`, content, and `prompt_type = experimental`
- **THEN** the `prompts` row stores `prompt_type = experimental`
- **AND** fetching the prompt by name returns `prompt_type`

#### Scenario: A blank prompt_type is allowed
- **WHEN** a prompt is created without a `prompt_type`
- **THEN** the row is stored with a null/blank `prompt_type`
- **AND** no validation error is raised

#### Scenario: Seeded prompts are tagged baseline
- **WHEN** `seed_contract_prompts.py` runs
- **THEN** each of the 19 seeded prompts has `prompt_type = baseline`
- **AND** re-running the seeder is idempotent and preserves the `baseline` tag on seeded names

### Requirement: Practical Contract Type Drafting Prompts
The system SHALL seed a matching set of 22 per-type drafting prompts for the practical (中国合同分类法 Part 2) contract types, one per practical rubric type key: `company_formation`, `equity_transfer`, `capital_increase`, `merger_acquisition`, `equity_incentive`, `vam_agreement`, `equity_holding_in_trust`, `real_estate_sale`, `real_estate_lease`, `employment`, `labor_dispatch`, `ip_license`, `franchise`, `real_estate_development`, `insurance`, `trust`, `private_equity_fund`, `software_development`, `film_production`, `talent_agency`, `ppp_project`, `tourism_service`. Each SHALL be named `draft_<type>`, with `contract_type` set to the type key (loose coupling, no foreign key), `purpose = drafting`, `source = local`, `prompt_type = baseline`, and a `content` body that is a Chinese drafting instruction tailored to that type's mandatory clauses (mirroring the per-type rubric theme). The seeding script (`scripts/seed_contract_prompts.py`) SHALL seed both the 民法典 prompts and these practical prompts in one idempotent pass and SHALL NOT modify any row in `rubrics` or `criteria`.

#### Scenario: Seed the 22 practical-type prompts
- **WHEN** `seed_contract_prompts.py` runs against a database that already has the 19 民法典 drafting prompts
- **THEN** 22 new `draft_<type>` prompt rows are inserted with `contract_type` = the type key, `purpose = drafting`, `source = local`, and `prompt_type = baseline`
- **AND** each prompt's `content` is a Chinese drafting instruction for that practical type's mandatory clauses
- **AND** the 19 民法典 prompts are unchanged

#### Scenario: Re-seeding practical-type prompts is idempotent
- **WHEN** `seed_contract_prompts.py` is run a second time
- **THEN** the `prompts` row count is unchanged
- **AND** no duplicate prompt rows are created
- **AND** the `rubrics` and `criteria` row counts are unchanged

#### Scenario: Practical prompts are tagged baseline and loosely coupled
- **WHEN** the 22 practical prompts are fetched
- **THEN** each has `prompt_type = baseline` and `contract_type` equal to its type key
- **AND** no foreign key binds the prompt's `contract_type` to a rubric, so deleting or renaming a rubric does not invalidate the prompt

#### Scenario: Practical prompt type keys match the practical rubric type keys
- **WHEN** the practical prompt `contract_type` values and the practical rubric `<type>` segments are compared
- **THEN** the two sets of type keys are identical
- **AND** each `draft_<type>` prompt corresponds to exactly one `contract_<type>_v1` rubric

### Requirement: Law-Refined Variant Drafting Prompts
The system SHALL seed a second set of per-contract-type drafting prompts - the **law-refined** variants - one per contract type key (the same 41 keys covered by the baseline: 19 民法典 types + 22 practical types). Each SHALL be named `draft_<type>_v2`, with `contract_type` set to the type key (loose coupling, no foreign key), `purpose = drafting`, `source = local`, and `prompt_type = law-refined`. Each prompt's `content` SHALL be a Chinese drafting instruction whose mandatory-clause list is grounded in that type's law_info survey - explicitly naming the governing statutes, judicial interpretations, and (where relevant) article ranges (e.g. for `sale`: 《民法典》合同编第八章买卖合同第595–647条、法释〔2020〕17号、法释〔2023〕13号). The seeding script (`scripts/seed_contract_prompts.py`) SHALL seed the baseline `draft_<type>` prompts AND these `draft_<type>_v2` prompts in one idempotent pass, SHALL NOT modify any baseline `draft_<type>` row (upsert matches by name; the names differ), and SHALL NOT modify any row in `rubrics` or `criteria`.

#### Scenario: Seed the 41 law-refined variant prompts
- **WHEN** `seed_contract_prompts.py` runs against a database that already has the 41 baseline `draft_<type>` prompts
- **THEN** 41 new `draft_<type>_v2` prompt rows are inserted with `contract_type` = the type key, `purpose = drafting`, `source = local`, and `prompt_type = law-refined`
- **AND** each prompt's `content` names the governing statutes/interpretations drawn from that type's law_info survey
- **AND** the 41 baseline `draft_<type>` prompts are unchanged

#### Scenario: Re-seeding law-refined prompts is idempotent
- **WHEN** `seed_contract_prompts.py` is run a second time
- **THEN** the `prompts` row count is unchanged
- **AND** no duplicate prompt rows are created
- **AND** the `rubrics` and `criteria` row counts are unchanged

#### Scenario: Baseline prompts are not modified by the v2 seed
- **WHEN** `seed_contract_prompts.py` runs after the v2 variants already exist
- **THEN** every baseline `draft_<type>` row retains its original `content` and `prompt_type = baseline`
- **AND** no baseline row is overwritten by the seeder

#### Scenario: Law-refined prompts are tagged and loosely coupled
- **WHEN** the 41 `draft_<type>_v2` prompts are fetched
- **THEN** each has `prompt_type = law-refined` and `contract_type` equal to its type key
- **AND** no foreign key binds the prompt's `contract_type` to a rubric, so deleting or renaming a rubric does not invalidate the prompt

#### Scenario: Law-refined prompts are usable in compare runs
- **WHEN** a compare run is created using a `draft_<type>_v2` prompt
- **THEN** the run's `prompt_name` and `prompt_type` snapshot columns record `draft_<type>_v2` and `law-refined` respectively
- **AND** the baseline `draft_<type>` prompt can be compared against the v2 variant in the same compare run

