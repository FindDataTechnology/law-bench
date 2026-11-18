## ADDED Requirements

### Requirement: Generation Prompt Storage
The system SHALL store generation prompts in a `prompts` table within `db/evaluation_rules.db`. Each prompt SHALL have a unique `name`, a `contract_type` (e.g. `sale`), a `purpose` (e.g. `drafting`), a `content` body (the prompt text), a `source`, an optional `description`, and a `created_at` timestamp. The `prompts` table SHALL be created by the same schema source of truth that creates `rubrics` and `criteria` (`scripts/extract_harbor_rules.py`'s `SCHEMA`), so any seeder that calls `create_schema()` establishes it.

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
