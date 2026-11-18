## ADDED Requirements

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
