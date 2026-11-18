# evaluation-rules-web Specification

## Purpose
Give operators a web surface to browse, create, edit, and delete local evaluation rubrics and their criteria without touching the database directly.

## Requirements
### Requirement: Browse Evaluation Rubrics
The system SHALL present a list of all rubrics, each showing its name (rendered as a localized display title per `data-label-i18n`, with the machine `name` retained as the link target), its `context` rendered as a localized label in the active locale (falling back to the raw key when unmapped), its `source` rendered as a localized source label (per the web-i18n Localized Rubric Source Display requirement) rather than the raw source string, and its criterion count. Harbor rubrics (`source` starting with `harbor:`) and local rubrics (`source = local`) SHALL be shown together.

#### Scenario: List all rubrics
- **WHEN** a user opens the rubrics listing
- **THEN** every rubric stored in the database is shown with its localized display title, context, source, and the number of criteria it contains
- **AND** harbor rubrics and local rubrics are listed together

#### Scenario: Localized title and context in Chinese
- **WHEN** a user opens the rubrics listing with locale `zh` and a rubric has `name = contract_sale_v1`, `context = contract`
- **THEN** the row shows the display title `买卖合同评价规则` and the context label `合同`
- **AND** the link target remains `/rubrics/contract_sale_v1`

#### Scenario: Unknown values fall back to the raw key
- **WHEN** a rubric has a user-authored `name` `my_rubric` and an unmapped `context` `custom_ctx`
- **THEN** the listing shows `my_rubric` and `custom_ctx` unchanged

#### Scenario: Source column localized
- **WHEN** a user opens the rubrics listing with locale `zh`
- **THEN** the source column renders localized labels (e.g. `本地` for local, `Harbor v0.4.2` for harbor) rather than the raw `local` / `harbor:v0.4.2`

### Requirement: Rubric Detail View
The system SHALL show a single rubric's name (as a localized display title per `data-label-i18n`), its `context` rendered as a localized label in the active locale (raw-key fallback), its `source` rendered as a localized source label, `source_path`, and `description`, followed by its criteria ordered by `ordinal`, each showing its name, description, and guidance. The machine `name` SHALL remain the URL path. Each criterion's name, description, and guidance SHALL render in the active locale where a translation exists, falling back to the stored text otherwise (per the web-i18n Localized Data-Value Labels requirement).

#### Scenario: View a rubric and its criteria
- **WHEN** a user opens a rubric
- **THEN** its localized display title, context, source, source_path, and description are displayed
- **AND** its criteria are listed in `ordinal` order, each showing name, description, and guidance

#### Scenario: Detail title and context localize in Chinese
- **WHEN** a user opens rubric `contract_lease_v1` with locale `zh` and its `context` is `contract`
- **THEN** the heading shows `租赁合同评价规则` and the context field shows `合同`

#### Scenario: Criterion content localized when zh
- **WHEN** a user opens a harbor rubric detail page with locale `zh`
- **THEN** each seeded criterion's title, description, and guidance render in Chinese where a translation exists
- **AND** user-authored or untranslated criteria render their stored text unchanged

#### Scenario: Source row localized
- **WHEN** a user opens a rubric detail page with locale `zh`
- **THEN** the source row renders a localized label (e.g. `本地` / `Harbor v0.4.2`) rather than the raw source string

### Requirement: Create Local Rubric
The system SHALL allow creating a new locally-authored rubric with `source = local`, a name, a context, a description, and zero or more initial criteria.

#### Scenario: Create a new local rubric with criteria
- **WHEN** a user submits a new rubric with name `contract_v2`, context `contract`, a description, and two criteria
- **THEN** a rubric row is stored with `source = local`
- **AND** the two criteria are stored ordered by their submitted position

#### Scenario: Reject duplicate local rubric name
- **WHEN** a user submits a local rubric whose name already belongs to an existing local rubric
- **THEN** the submission is rejected with a clear validation error
- **AND** no rubric or criterion row is created

### Requirement: Edit Local Rubric Metadata
The system SHALL allow editing a local rubric's name, context, and description without affecting its criteria.

#### Scenario: Rename a local rubric
- **WHEN** a user changes a local rubric's name and saves
- **THEN** the rubric row is updated with the new name
- **AND** its criteria remain unchanged

### Requirement: Manage Criteria of a Local Rubric
The system SHALL allow adding, editing, deleting, and reordering criteria within a local rubric. Criterion names SHALL be unique within a rubric.

#### Scenario: Reorder criteria
- **WHEN** a user moves a criterion to a new position and saves
- **THEN** the `ordinal` values of the rubric's criteria are reassigned to match the new order

#### Scenario: Reject duplicate criterion name within a rubric
- **WHEN** a user adds or renames a criterion to a name already used by another criterion in the same rubric
- **THEN** the change is rejected with a clear validation error
- **AND** no duplicate criterion row is created

### Requirement: Delete Local Rubric
The system SHALL allow deleting a local rubric. Deleting a rubric SHALL also delete all of its criteria.

#### Scenario: Deleting a local rubric cascades to its criteria
- **WHEN** a user deletes a local rubric
- **THEN** the rubric row and all of its criteria rows are removed from the database

### Requirement: Harbor Rubric Immutability
The system SHALL treat rubrics whose `source` starts with `harbor:` as read-only. It SHALL reject any attempt to edit or delete a harbor rubric or any of its criteria through the web interface.

#### Scenario: Editing or deleting a harbor rubric is rejected
- **WHEN** a user attempts to edit or delete a harbor rubric or one of its criteria
- **THEN** the action is rejected with a clear error explaining that harbor rubrics are managed by extraction
- **AND** no harbor rubric or harbor criterion row is modified or deleted

### Requirement: Harbor Re-extraction Trigger
The system SHALL provide a control that re-runs the harbor rubric extraction, refreshing harbor rubrics to match the installed harbor package while leaving local rubrics untouched.

#### Scenario: Refresh harbor rubrics
- **WHEN** a user triggers harbor re-extraction
- **THEN** the harbor extraction script runs
- **AND** harbor rubrics and their criteria are refreshed to match the installed harbor package
- **AND** local rubrics and their criteria remain unchanged

### Requirement: JSON API
The system SHALL expose the list of rubrics, a single rubric, and a rubric's criteria as JSON so the same data is scriptable.

#### Scenario: Fetch rubrics as JSON
- **WHEN** a client requests the rubrics JSON endpoint
- **THEN** a JSON array of rubrics is returned, each with name, context, source, and criterion count

#### Scenario: Fetch a single rubric and its criteria as JSON
- **WHEN** a client requests the JSON endpoint for a rubric
- **THEN** the rubric's metadata and its criteria (ordered by `ordinal`) are returned as JSON

### Requirement: Local-only Operation
The system SHALL run as a local process bound to `127.0.0.1` with no authentication, and its dependencies SHALL be installed via `uv sync`.

#### Scenario: Run the web app locally
- **WHEN** a user runs the web app start command
- **THEN** an HTTP server starts bound to `127.0.0.1`
- **AND** all required dependencies are satisfied by running `uv sync`
