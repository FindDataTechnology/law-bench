## ADDED Requirements

### Requirement: Browse Evaluation Rubrics
The system SHALL present a list of all rubrics, each showing its name, context, source, and criterion count. Harbor rubrics (`source` starting with `harbor:`) and local rubrics (`source = local`) SHALL be shown together.

#### Scenario: List all rubrics
- **WHEN** a user opens the rubrics listing
- **THEN** every rubric stored in the database is shown with its name, context, source, and the number of criteria it contains
- **AND** harbor rubrics and local rubrics are listed together

### Requirement: Rubric Detail View
The system SHALL show a single rubric's name, context, source, source_path, and description, followed by its criteria ordered by `ordinal`, each showing its name, description, and guidance.

#### Scenario: View a rubric and its criteria
- **WHEN** a user opens a rubric
- **THEN** its name, context, source, source_path, and description are displayed
- **AND** its criteria are listed in `ordinal` order, each showing name, description, and guidance

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
