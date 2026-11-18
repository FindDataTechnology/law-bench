# Generation Prompts Web Specification

## Purpose
Web management UI (HTML + JSON API) for generation prompts.
## Requirements
### Requirement: Browse Generation Prompts
The system SHALL present a list of all generation prompts, each showing its name (rendered as a localized display title per `data-label-i18n`, with the machine `name` retained as the link target), its `contract_type` and `purpose` rendered as localized labels in the active locale (falling back to the raw key when unmapped), its `prompt_type` (rendered as a localized label with raw-key fallback), and its `source`. A top-level navigation link SHALL join the prompt management area with the existing rubric management area in the same web app.

#### Scenario: List all prompts
- **WHEN** a user opens the prompts listing
- **THEN** every prompt stored in the database is shown with its localized display title, contract_type, purpose, prompt_type, and source

#### Scenario: Localized labels and title in Chinese
- **WHEN** a user opens the prompts listing with locale `zh` and a prompt has `name = draft_sale`, `contract_type = sale`, `purpose = drafting`, `prompt_type = baseline`
- **THEN** the row shows the display title `买卖合同起草`, the contract_type label `买卖合同`, the purpose label `起草`, and the prompt_type label `基线`
- **AND** the link target remains `/prompts/draft_sale`

#### Scenario: Unknown values fall back to the raw key
- **WHEN** a prompt has an unmapped `contract_type` value `custom_type` and a user-authored `name` `my_prompt`
- **THEN** the listing shows `custom_type` and `my_prompt` unchanged

### Requirement: Prompt Detail View
The system SHALL show a single prompt's name (as a localized display title per `data-label-i18n`), its `contract_type` and `purpose` rendered as localized labels in the active locale (raw-key fallback), its `prompt_type` (localized label with raw-key fallback), `source`, `description`, and its full `content` body. The machine `name` SHALL remain the URL path.

#### Scenario: View a prompt
- **WHEN** a user opens a prompt
- **THEN** its localized display title, contract_type, purpose, prompt_type, source, description, and full content are displayed

#### Scenario: Detail labels localize in Chinese
- **WHEN** a user opens prompt `draft_loan` with locale `zh`
- **THEN** the heading shows `借款合同起草` and the contract_type and purpose fields show `借款合同` and `起草`

### Requirement: Create Prompt
The system SHALL allow creating a new generation prompt with a name, contract_type, purpose, content, and optional description. The name SHALL be unique among prompts.

#### Scenario: Create a new prompt
- **WHEN** a user submits a new prompt with name `draft_lease`, contract_type `lease`, purpose `drafting`, and a content body
- **THEN** a prompt row is stored with `source = local`
- **AND** the user is redirected to the new prompt's detail view

#### Scenario: Reject duplicate prompt name
- **WHEN** a user submits a prompt whose name already belongs to an existing prompt
- **THEN** the submission is rejected with a clear validation error
- **AND** no prompt row is created

### Requirement: Edit Prompt
The system SHALL allow editing a prompt's name, contract_type, purpose, content, and description.

#### Scenario: Edit a prompt's content
- **WHEN** a user changes a prompt's content body and saves
- **THEN** the prompt row is updated with the new content
- **AND** the user is redirected back to the prompt's detail view

### Requirement: Delete Prompt
The system SHALL allow deleting a generation prompt.

#### Scenario: Delete a prompt
- **WHEN** a user deletes a prompt
- **THEN** the prompt row is removed from the database
- **AND** the user is redirected to the prompts listing

### Requirement: Prompt JSON API
The system SHALL expose the list of prompts, a single prompt, and prompt create/update/delete operations as JSON under `/api/prompts`, so the same data is scriptable. Write operations SHALL delegate to the same manage layer the HTML flows use.

#### Scenario: Fetch prompts as JSON
- **WHEN** a client requests the prompts JSON endpoint
- **THEN** a JSON array of prompts is returned, each with name, contract_type, purpose, and source

#### Scenario: Create a prompt via JSON
- **WHEN** a client POSTs a valid prompt payload to `/api/prompts`
- **THEN** the prompt is created and returned as JSON with status 201

#### Scenario: Manage-layer errors map to HTTP statuses
- **WHEN** a prompt write fails validation, conflict, or not-found
- **THEN** the response uses the same HTTP status mapping as the rubric API (400, 409, 404 respectively)

### Requirement: Prompt Type in the Management UI
The prompt management UI (list, form, detail) SHALL surface `prompt_type` as an editable field. The list and detail view SHALL display each prompt's `prompt_type` as a localized label in the active locale (raw-key fallback). The form SHALL accept a `prompt_type` input on create and edit; the form input value SHALL be the raw machine `prompt_type` value (so storage is unaffected), with a localized placeholder. The JSON API models (`PromptCreate`, `PromptUpdate`) and endpoints SHALL carry `prompt_type` through create/update/read as the raw machine value.

#### Scenario: Create a prompt with a type from the UI
- **WHEN** the user creates a prompt via the form, filling `prompt_type = experimental`
- **THEN** the stored prompt has `prompt_type = experimental`
- **AND** the detail page shows the localized label for `experimental` (e.g. `实验` in `zh`)

#### Scenario: Edit a prompt's type
- **WHEN** the user edits a prompt and changes `prompt_type` from `experimental` to `improved`
- **THEN** the stored `prompt_type` becomes `improved`

#### Scenario: The list shows localized prompt types
- **WHEN** the user views `/prompts` with locale `zh`
- **THEN** each row shows its `prompt_type` as a localized label (e.g. `baseline` -> `基线`), blank when unset

#### Scenario: The API carries prompt_type as the raw machine value
- **WHEN** `POST /api/prompts` or `PATCH /api/prompts/{name}` is called with a `prompt_type`
- **THEN** the raw field is persisted and returned by `GET /api/prompts/{name}` (the API is unaffected by localization)
