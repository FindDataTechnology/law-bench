## ADDED Requirements

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
