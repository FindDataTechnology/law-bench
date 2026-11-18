## ADDED Requirements

### Requirement: Law-Info and Law-References Navigation Labels
The system SHALL render navigation links to the `/law-info` and `/law-references` pages in the topbar, with localized labels drawn from the single chrome translation source of truth. The `zh` and `en` catalogs SHALL expose identical key sets for these new nav keys (`nav.law_info`, `nav.law_references`), preserving the catalog parity contract.

#### Scenario: Nav links are present and localized
- **WHEN** a user views any page with locale `zh`
- **THEN** the topbar shows a localized link to `/law-info` and a localized link to `/law-references`
- **AND** with locale `en` the same links render with English labels

#### Scenario: Nav key parity holds
- **WHEN** the chrome catalog is loaded for `zh` and `en`
- **THEN** both `nav.law_info` and `nav.law_references` exist with non-empty values in each locale
