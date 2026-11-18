# Web i18n Specification

## ADDED Requirements

### Requirement: Supported Locales
The system SHALL support two locales: `zh` (Chinese) and `en` (English). `zh` SHALL be the default locale when no choice is expressed by the user or browser.

#### Scenario: Default locale with no signal
- **WHEN** a request arrives with no `?lang` query param, no `lang` cookie, and no `Accept-Language` header
- **THEN** the active locale is `zh`

#### Scenario: Unknown locale falls back to default
- **WHEN** a request carries `?lang=fr`
- **THEN** the active locale falls back to `zh` (the default) and `fr` is not honored

### Requirement: Locale Resolution
The system SHALL resolve the active locale per request in the order: `?lang` query param ▶ `lang` cookie ▶ `Accept-Language` header ▶ default (`zh`). The resolved locale SHALL be validated against the supported set; an unsupported value at any step SHALL fall through to the next step.

#### Scenario: Explicit query param wins
- **WHEN** a request carries `?lang=en` and the `lang` cookie is `zh`
- **THEN** the active locale is `en`

#### Scenario: Cookie honored when no query param
- **WHEN** a request carries no `?lang` and the `lang` cookie is `en`
- **THEN** the active locale is `en`

#### Scenario: Accept-Language used on first visit
- **WHEN** a request carries no `?lang`, no `lang` cookie, and `Accept-Language: en-US,en;q=0.9`
- **THEN** the active locale is `en` (first supported match)

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
The system SHALL render all UI chrome - navigation, page headings, form labels, **table column headers**, hints, and button labels - in the active locale, drawn from a single translation source of truth. No hard-coded English UI string SHALL remain in the templates.

#### Scenario: Table headers localized
- **WHEN** a user opens the rubrics listing with locale `zh`
- **THEN** the table column headers render as Chinese (e.g. 名称 / 上下文 / 来源 / 评分项数)

#### Scenario: Nav and headings localized
- **WHEN** a user views any page with locale `en`
- **THEN** the navigation links, page headings, and form labels render in English

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
