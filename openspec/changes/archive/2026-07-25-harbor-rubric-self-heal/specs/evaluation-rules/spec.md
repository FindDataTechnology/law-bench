## MODIFIED Requirements

### Requirement: Harbor Provenance and Idempotent Extraction
The system SHALL extract harbor's rubrics from the installed harbor package's TOML rubric files when harbor is installed, recording their provenance (`source`, `source_path`, `context`) and the installed harbor version. When the harbor package cannot be located on disk, the system SHALL fall back to a bundled seed copy of harbor's rubric TOMLs shipped in the repository, recording `source = harbor:v0.20.0`. Re-running the extraction SHALL be idempotent: it SHALL NOT create duplicate rubrics or criteria, and SHALL NOT modify or delete rows whose `source` is not `harbor`.

#### Scenario: Re-run extraction does not duplicate
- **WHEN** the extraction script is run a second time
- **THEN** the rubric and criteria row counts are unchanged
- **AND** no duplicate rows are created

#### Scenario: Local rows are preserved across re-extraction
- **WHEN** a local contract rubric exists (`source = local`) and the extraction script runs
- **THEN** the local rubric and its criteria remain unchanged

#### Scenario: Harbor not installed falls back to the bundled seed
- **WHEN** the harbor package cannot be located on disk
- **THEN** the extraction script loads harbor rubrics from the bundled seed TOMLs shipped in the repository
- **AND** exits 0, recording `source = harbor:v0.20.0`
- **AND** does not raise an error requiring harbor to be installed

## ADDED Requirements

### Requirement: Bundled Harbor Rubric Seed and Startup Self-Heal
The system SHALL ship a bundled copy of harbor's rubric TOMLs (`task_quality` with 11 criteria, `trial_behavior` with 2 criteria) in the repository, pinned to harbor v0.20.0. The system SHALL provide an importable seeding entrypoint that idempotently ensures harbor rubrics are present in a target database: it SHALL create the schema if absent and upsert every harbor rubric from the installed harbor package when available, otherwise from the bundled seed. The heal SHALL be scoped to rows whose `source` is `harbor` (`source LIKE 'harbor:%'`); it SHALL NOT modify or delete local rubrics, prompts, or evaluation-run data. The container SHALL run this heal on every startup before serving requests, so a stale or partially-seeded database self-heals without a volume reset or rebuild.

#### Scenario: Empty database is healed
- **WHEN** the seeding entrypoint runs against a database with no `rubrics` table
- **THEN** the schema is created and the two harbor rubrics are present with 13 total criteria
- **AND** each harbor rubric has `source = harbor:v0.20.0`

#### Scenario: Stale volume self-heals on container startup
- **WHEN** the container starts with a volume whose database has local rubrics but no harbor rubrics
- **THEN** the startup heal inserts the two harbor rubrics and their 13 criteria
- **AND** the existing local rubrics and any evaluation-run rows remain unchanged

#### Scenario: Heal is idempotent
- **WHEN** the seeding entrypoint runs a second time against an already-healed database
- **THEN** the harbor rubric and criteria counts are unchanged
- **AND** no duplicate rows are created

#### Scenario: Installed harbor takes precedence over the bundle
- **WHEN** the harbor package is installed and the seeding entrypoint runs
- **THEN** criteria are loaded from the installed harbor package
- **AND** `source` records the installed harbor's version

#### Scenario: Re-extract harbor button works without harbor installed
- **WHEN** the "Re-extract harbor" control is triggered in a container where harbor is not installed
- **THEN** the request succeeds (exit 0) by loading from the bundled seed
- **AND** the refreshed rubric list is returned
