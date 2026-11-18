## MODIFIED Requirements

### Requirement: Localized UI Chrome
The system SHALL render all UI chrome - navigation, page headings, form labels, **table column headers**, hints, button labels, and **input placeholders** - in the active locale, drawn from a single translation source of truth. No hard-coded English UI string SHALL remain in the templates, including placeholder text on form inputs rendered server-side or injected client-side.

#### Scenario: Table headers localized
- **WHEN** a user opens the rubrics listing with locale `zh`
- **THEN** the table column headers render as Chinese (e.g. 名称 / 上下文 / 来源 / 评分项数)

#### Scenario: Nav and headings localized
- **WHEN** a user views any page with locale `en`
- **THEN** the navigation links, page headings, and form labels render in English

#### Scenario: Input placeholders localized
- **WHEN** a user opens the rubric detail page's add-criterion form with locale `zh`
- **THEN** the criterion-name input placeholder renders in Chinese, not the hard-coded English `e.g. party_identification`
- **AND** the same placeholder rendered client-side by `app.js` for new criterion rows also follows the active locale

## ADDED Requirements

### Requirement: Localized Data-Value Labels
The system SHALL localize data values rendered in templates - the machine keys stored in the database (contract type, purpose, prompt type, context, mode, and seeded criterion content) - via a per-locale data-label catalog that is separate from the UI-chrome catalog. For each value the system SHALL resolve a localized display label; when no translation exists for a value (including user-authored free text, future unmapped keys, and the `en` locale for seeded criterion content), the system SHALL fall back to the raw stored value unchanged. The system SHALL never raise, never blank, and never alter the underlying machine key, which remains the canonical database / URL / join identifier.

#### Scenario: Seeded contract type localized
- **WHEN** a rubric or prompt carries `contract_type = sale` and the active locale is `zh`
- **THEN** the rendered display label is `买卖合同`

#### Scenario: Unmapped data value falls back to raw
- **WHEN** a user-authored prompt carries `prompt_type = my_custom_variant` not present in the catalog
- **THEN** the rendered display is the raw `my_custom_variant`, regardless of locale

#### Scenario: Seeded criterion content localized when zh
- **WHEN** a harbor rubric criterion named `behavior_in_task_description` is rendered with locale `zh`
- **THEN** its title, description, and guidance render from the `zh` criterion catalog
- **AND** the underlying stored `name` is unchanged as the database / URL key

#### Scenario: Contract criterion title localized when zh
- **WHEN** a contract rubric criterion named `party_identification` is rendered with locale `zh`
- **THEN** its heading renders the localized `zh` title (e.g. `合同主体识别`) instead of the raw snake_case `name`
- **AND** its description and guidance render the stored Chinese text unchanged (the contract seed already stores them in Chinese)

#### Scenario: Criterion content falls back to stored text
- **WHEN** a local user-authored criterion not present in the catalog is rendered, or any criterion is rendered with locale `en`
- **THEN** its title, description, and guidance render the raw stored text unchanged

### Requirement: Localized Guidance Tokens
For `zh` guidance with no catalog entry, the system SHALL localize the English `PASS if` / `FAIL if` tokens in the stored guidance text to `通过条件：` / `不通过条件：` (matching the form-label convention), so seeded criteria whose guidance is authored as `PASS if … / FAIL if …` render fully in Chinese. The `en` locale and catalogued `zh` guidance SHALL be left untouched.

#### Scenario: Contract guidance tokens localized when zh
- **WHEN** a criterion with stored guidance `PASS if 每一方均列明；FAIL if 任一主体未列明。` is rendered with locale `zh`
- **THEN** the read-only guidance display shows `通过条件：每一方均列明；不通过条件：任一主体未列明。`

#### Scenario: Guidance untouched for en and catalogued zh
- **WHEN** the same criterion is rendered with locale `en`, or a harbor criterion with a `zh` guidance catalog entry is rendered
- **THEN** the guidance renders without token substitution

### Requirement: Localized Rubric Source Display
The system SHALL render a rubric's `source` field as a localized, human-readable label rather than the raw machine string. `local` SHALL render as the localized "local" label (e.g. `本地` for `zh`, `local` for `en`); a harbor source of the form `harbor:vX.Y.Z` SHALL render as `Harbor v{ver}` with the version extracted from the string. Any other source value SHALL fall back to the raw string unchanged.

#### Scenario: Local source label
- **WHEN** a local rubric (`source = local`) is rendered with locale `zh`
- **THEN** the source display is `本地`

#### Scenario: Harbor source label
- **WHEN** a harbor rubric (`source = harbor:v0.4.2`) is rendered
- **THEN** the source display is `Harbor v0.4.2`

#### Scenario: Unknown source falls back
- **WHEN** a rubric carries `source = import:foo` not matching a known shape
- **THEN** the source display is the raw `import:foo`
