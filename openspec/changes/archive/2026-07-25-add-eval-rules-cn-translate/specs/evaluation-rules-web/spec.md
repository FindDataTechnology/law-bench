## MODIFIED Requirements

### Requirement: Browse Evaluation Rubrics
The system SHALL present a list of all rubrics, each showing its name, context, source, and criterion count. Harbor rubrics (`source` starting with `harbor:`) and local rubrics (`source = local`) SHALL be shown together. The `source` column SHALL render a localized source label (per the web-i18n Localized Rubric Source Display requirement) rather than the raw source string.

#### Scenario: List all rubrics
- **WHEN** a user opens the rubrics listing
- **THEN** every rubric stored in the database is shown with its name, context, source, and the number of criteria it contains
- **AND** harbor rubrics and local rubrics are listed together

#### Scenario: Source column localized
- **WHEN** a user opens the rubrics listing with locale `zh`
- **THEN** the source column renders localized labels (e.g. `本地` for local, `Harbor v0.4.2` for harbor) rather than the raw `local` / `harbor:v0.4.2`

### Requirement: Rubric Detail View
The system SHALL show a single rubric's name, context, source, source_path, and description, followed by its criteria ordered by `ordinal`, each showing its name, description, and guidance. The `source` field SHALL render a localized source label. Each criterion's name, description, and guidance SHALL render in the active locale where a translation exists, falling back to the stored text otherwise (per the web-i18n Localized Data-Value Labels requirement).

#### Scenario: View a rubric and its criteria
- **WHEN** a user opens a rubric
- **THEN** its name, context, source, source_path, and description are displayed
- **AND** its criteria are listed in `ordinal` order, each showing name, description, and guidance

#### Scenario: Criterion content localized when zh
- **WHEN** a user opens a harbor rubric detail page with locale `zh`
- **THEN** each seeded criterion's title, description, and guidance render in Chinese where a translation exists
- **AND** user-authored or untranslated criteria render their stored text unchanged

#### Scenario: Source row localized
- **WHEN** a user opens a rubric detail page with locale `zh`
- **THEN** the source row renders a localized label (e.g. `本地` / `Harbor v0.4.2`) rather than the raw source string
