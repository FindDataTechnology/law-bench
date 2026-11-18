## ADDED Requirements

### Requirement: Rubric and Criterion Storage
The system SHALL store evaluation rubrics and their criteria in a SQLite database at `db/evaluation_rules.db`. Each rubric SHALL have a name, context, source, source_path, and description. Each criterion SHALL belong to exactly one rubric and SHALL have a name, description, guidance, and ordinal. The combination of rubric and criterion name SHALL be unique.

#### Scenario: Store a harbor rubric with its criteria
- **WHEN** the extraction script runs against harbor's `default-rubric.toml`
- **THEN** a `task_quality` rubric row is stored with `source = harbor:v0.20.0`, `context = check`, and `source_path` pointing at the harbor TOML file
- **AND** each of its 11 criteria is stored with name, description, and guidance

#### Scenario: Query criteria of a rubric
- **WHEN** a caller queries criteria by rubric name
- **THEN** all criteria for that rubric are returned ordered by `ordinal`

### Requirement: Harbor Provenance and Idempotent Extraction
The system SHALL extract harbor's rubrics from the installed harbor package's TOML rubric files and record their provenance (`source`, `source_path`, `context`). Re-running the extraction SHALL be idempotent: it SHALL NOT create duplicate rubrics or criteria, and SHALL NOT modify or delete rows whose `source` is not `harbor`.

#### Scenario: Re-run extraction does not duplicate
- **WHEN** the extraction script is run a second time
- **THEN** the rubric and criteria row counts are unchanged
- **AND** no duplicate rows are created

#### Scenario: Local rows are preserved across re-extraction
- **WHEN** a local contract rubric exists (`source = local`) and the extraction script runs
- **THEN** the local rubric and its criteria remain unchanged

#### Scenario: Harbor not installed
- **WHEN** the harbor package cannot be located on disk
- **THEN** the extraction script fails with a clear error message indicating harbor must be installed (`uv tool install harbor`)

### Requirement: Extensibility for Local Rubrics
The schema SHALL support locally-authored rubrics distinct from harbor reference rubrics, identified by `source = local`. Local rubrics SHALL coexist with harbor rubrics in the same tables without conflict.

#### Scenario: Add a local contract rubric
- **WHEN** a local rubric is inserted with `source = local` and `context = contract`
- **THEN** it is stored alongside harbor rubrics
- **AND** it is not affected by subsequent harbor extractions
