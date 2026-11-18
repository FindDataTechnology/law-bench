## ADDED Requirements

### Requirement: Prompt Type in the Management UI
The prompt management UI (list, form, detail) SHALL surface `prompt_type` as an editable field. The list SHALL display each prompt's `prompt_type`; the form SHALL accept a `prompt_type` input on create and edit; the detail view SHALL show it. The JSON API models (`PromptCreate`, `PromptUpdate`) and endpoints SHALL carry `prompt_type` through create/update/read.

#### Scenario: Create a prompt with a type from the UI
- **WHEN** the user creates a prompt via the form, filling `prompt_type = experimental`
- **THEN** the stored prompt has `prompt_type = experimental`
- **AND** the detail page shows `experimental`

#### Scenario: Edit a prompt's type
- **WHEN** the user edits a prompt and changes `prompt_type` from `experimental` to `improved`
- **THEN** the stored `prompt_type` becomes `improved`

#### Scenario: The list shows prompt types
- **WHEN** the user views `/prompts`
- **THEN** each row shows its `prompt_type` (blank when unset)

#### Scenario: The API carries prompt_type
- **WHEN** `POST /api/prompts` or `PATCH /api/prompts/{name}` is called with a `prompt_type`
- **THEN** the field is persisted and returned by `GET /api/prompts/{name}`
