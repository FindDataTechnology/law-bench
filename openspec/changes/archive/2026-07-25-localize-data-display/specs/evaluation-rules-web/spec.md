# evaluation-rules-web Specification (delta)

## MODIFIED Requirements

### Requirement: Browse Evaluation Rubrics
The system SHALL present a list of all rubrics, each showing its name (rendered as a localized display title per `data-label-i18n`, with the machine `name` retained as the link target), its `context` rendered as a localized label in the active locale (falling back to the raw key when unmapped), its `source`, and its criterion count. Harbor rubrics (`source` starting with `harbor:`) and local rubrics (`source = local`) SHALL be shown together.

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

### Requirement: Rubric Detail View
The system SHALL show a single rubric's name (as a localized display title per `data-label-i18n`), its `context` rendered as a localized label in the active locale (raw-key fallback), `source`, `source_path`, and `description`, followed by its criteria ordered by `ordinal`, each showing its name, description, and guidance. The machine `name` SHALL remain the URL path.

#### Scenario: View a rubric and its criteria
- **WHEN** a user opens a rubric
- **THEN** its localized display title, context, source, source_path, and description are displayed
- **AND** its criteria are listed in `ordinal` order, each showing name, description, and guidance

#### Scenario: Detail title and context localize in Chinese
- **WHEN** a user opens rubric `contract_lease_v1` with locale `zh` and its `context` is `contract`
- **THEN** the heading shows `租赁合同评价规则` and the context field shows `合同`
