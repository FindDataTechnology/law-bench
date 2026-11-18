# Web i18n Specification

## Purpose

Multi-locale zh/en presentation layer for the evaluation-rules web app.
## Requirements
### Requirement: Supported Locales
The system SHALL support two locales: `zh` (Chinese) and `en` (English). `zh` SHALL be the default locale when no choice is expressed by the user. The browser's `Accept-Language` header SHALL NOT influence locale resolution; first-time visitors always land on `zh`.

#### Scenario: Default locale with no signal
- **WHEN** a request arrives with no `?lang` query param and no `lang` cookie (regardless of any `Accept-Language` header)
- **THEN** the active locale is `zh`

#### Scenario: Unknown locale falls back to default
- **WHEN** a request carries `?lang=fr`
- **THEN** the active locale falls back to `zh` (the default) and `fr` is not honored

### Requirement: Locale Resolution
The system SHALL resolve the active locale per request in the order: `?lang` query param ▶ `lang` cookie ▶ default (`zh`). The resolved locale SHALL be validated against the supported set; an unsupported value at any step SHALL fall through to the next step. The `Accept-Language` header SHALL be ignored at every step.

#### Scenario: Explicit query param wins
- **WHEN** a request carries `?lang=en` and the `lang` cookie is `zh`
- **THEN** the active locale is `en`

#### Scenario: Cookie honored when no query param
- **WHEN** a request carries no `?lang` and the `lang` cookie is `en`
- **THEN** the active locale is `en`

#### Scenario: Accept-Language ignored on first visit
- **WHEN** a request carries no `?lang`, no `lang` cookie, and `Accept-Language: en-US,en;q=0.9`
- **THEN** the active locale is `zh` (the `Accept-Language` header is not consulted)

### Requirement: Locale Persistence
The system SHALL set a `lang` cookie to the resolved locale on every request, so the user's choice (or the first-visit resolution) persists across requests and the system converges to a stable locale.

#### Scenario: Choice persists across requests
- **WHEN** a user selects `en` via the switcher and then navigates to another page without a `?lang` param
- **THEN** the active locale remains `en`

### Requirement: Language Switcher
The system SHALL render a language switcher in the topbar offering `EN` and `中文` links. Selecting a locale SHALL navigate to the current page with `?lang=<locale>`, which sets the cookie and re-renders the page in that locale. The active locale's link SHALL be marked as current.

#### Scenario: Switch to Chinese
- **WHEN** a user on an English page clicks `中文`
- **THEN** the page reloads with `?lang=zh`, the `lang` cookie is set to `zh`, and all chrome renders in Chinese

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

### Requirement: Localized Flash Messages
Flash messages SHALL be emitted as message keys (not localized strings) in the redirect URL. The system SHALL resolve a flash key against the active locale's catalog at render time, so flash URLs are locale-independent and render in whatever locale is active when the redirect lands. Dynamic flash text (e.g. tool stderr) that is not a known key SHALL be passed through unchanged.

#### Scenario: Flash renders in the active locale
- **WHEN** a rubric is created and the redirect lands with locale `zh`
- **THEN** the flash shows the Chinese translation of `flash.rubric_created`

#### Scenario: Interpolated flash localized
- **WHEN** a prompt named `draft_lease` is deleted and the redirect lands with locale `en`
- **THEN** the flash shows `Prompt 'draft_lease' deleted.`; with locale `zh` it shows the Chinese equivalent

### Requirement: Localized Compare Matrix
The compare matrix rendered by `app.js` SHALL render its labels (column headers, cell actions, status messages, and the dynamic criterion-row template labels) in the active locale, read from a locale catalog bootstrapped onto the page. The client SHALL degrade to English if the bootstrap is absent rather than throwing.

#### Scenario: Matrix headers localized
- **WHEN** a user opens a compare detail page with locale `zh`
- **THEN** the matrix's first column header and `view draft` buttons render in Chinese

#### Scenario: Status messages localized
- **WHEN** a compare run starts with locale `zh`
- **THEN** the status message shows the Chinese translation of `matrix.running`

### Requirement: Single Translation Source
The system SHALL maintain exactly one translation source of truth per locale, shared by the templates, the Python routes (flash messages), and the client (`app.js`). The `zh` and `en` catalogs SHALL expose identical key sets.

#### Scenario: Catalog parity
- **WHEN** the translation source is loaded
- **THEN** the set of keys in the `zh` catalog equals the set of keys in the `en` catalog

### Requirement: Correct Document Language
The system SHALL set the `<html lang>` attribute to the active locale code on every page, so accessibility tooling and browser hints follow the rendered language.

#### Scenario: HTML lang attribute follows locale
- **WHEN** a page renders with locale `zh`
- **THEN** the document is `<html lang="zh">`

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

### Requirement: Law-Info and Law-References Navigation Labels
The system SHALL render navigation links to the `/law-info` and `/law-references` pages in the topbar, with localized labels drawn from the single chrome translation source of truth. The `zh` and `en` catalogs SHALL expose identical key sets for these new nav keys (`nav.law_info`, `nav.law_references`), preserving the catalog parity contract.

#### Scenario: Nav links are present and localized
- **WHEN** a user views any page with locale `zh`
- **THEN** the topbar shows a localized link to `/law-info` and a localized link to `/law-references`
- **AND** with locale `en` the same links render with English labels

#### Scenario: Nav key parity holds
- **WHEN** the chrome catalog is loaded for `zh` and `en`
- **THEN** both `nav.law_info` and `nav.law_references` exist with non-empty values in each locale


### Requirement: Full Template Locale Parity

Every page template under `src/web/templates/` SHALL source its user-facing chrome strings (headings, table headers, labels, hints, buttons, flashes, placeholders, empty states) from the i18n catalog in both locales. After this change, no template SHALL carry hard-coded zh-only or en-only chrome strings, and the topbar language switch SHALL visibly change the chrome language on every destination it can reach, including dashboard, human review, clauses, contracts, contract detail, samples, search, law-catalog audit/review, login-denied, and law-info detail.

#### Scenario: Switching to English on a previously zh-only page

- **WHEN** an authenticated user opens `/dashboard?lang=en`
- **THEN** the page heading, section headings, stat labels, and table headers render in English

#### Scenario: Review pages follow the locale

- **WHEN** the annotator opens `/review?lang=en` and a pending task `/review/{id}?lang=en`
- **THEN** batch overview labels, verdict option labels, and action buttons render in English

#### Scenario: Law-catalog pages follow the locale

- **WHEN** the operator opens `/law-catalog/audit?lang=en` and `/law-catalog/review?lang=en`
- **THEN** headings, summary line labels, and action buttons render in English

### Requirement: Catalog Key Parity Guarantee

The system SHALL include an automated check that the zh and en locale trees expose the same key set, and that no locale file defines a key the other lacks. The check SHALL run as part of the test suite and SHALL fail on divergence.

#### Scenario: A key added only to zh

- **WHEN** a developer adds `empty.samples` to the zh catalog without an en counterpart
- **THEN** the parity test SHALL fail naming the missing key path

#### Scenario: Route-level labels are covered

- **WHEN** the parity check runs against review verdict labels and law-catalog mapping labels that moved into the catalog
- **THEN** both locales SHALL contain those keys and the check SHALL pass
