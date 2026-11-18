# generation-prompts Specification (delta)

## MODIFIED Requirements

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
