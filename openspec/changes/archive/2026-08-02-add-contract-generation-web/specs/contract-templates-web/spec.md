## ADDED Requirements

### Requirement: Browse Contract Classes
The system SHALL expose `GET /contracts` returning HTML that lists every contract class (key + zh_name) with a link to its detail page.

#### Scenario: List contracts on the web
- **WHEN** a client requests `GET /contracts`
- **THEN** the response is HTML listing all 41 contract classes, each linking to `/contracts/{key}`

### Requirement: Contract Detail Page
The system SHALL expose `GET /contracts/{contract_type}` returning HTML that shows, for the contract class: the rendered template content, each slot with its instruction (`label`, `description`, `example`, `required`), the per-type 法律法规 grouped by category, and download links for the DOCX and PDF. It SHALL return 404 for an unknown contract type.

#### Scenario: View a contract detail page
- **WHEN** a client requests `GET /contracts/sale`
- **THEN** the response is HTML containing the sale contract template, its slots with their instructions, its 法律法规, and links to `/contracts/sale/download/docx` and `/contracts/sale/download/pdf`

#### Scenario: Unknown contract type returns 404
- **WHEN** a client requests `GET /contracts/does_not_exist`
- **THEN** the response status is 404

### Requirement: Download Generated Document
The system SHALL expose `GET /contracts/{contract_type}/download/{format}` that generates (if not already cached) and streams the contract's `.docx` (`format=docx`) or `.pdf` (`format=pdf`) using the same `src.contracts` generation API as the CLI. It SHALL return 404 for an unknown contract type and 400 for an unsupported format.

#### Scenario: Download a PDF
- **WHEN** a client requests `GET /contracts/sale/download/pdf` and a PDF backend is available
- **THEN** the response streams an `application/pdf` body with filename `sale.pdf`

#### Scenario: Download a DOCX
- **WHEN** a client requests `GET /contracts/sale/download/docx`
- **THEN** the response streams the generated `.docx` with an appropriate content type

#### Scenario: Unsupported format returns 400
- **WHEN** a client requests `GET /contracts/sale/download/rtf`
- **THEN** the response status is 400

#### Scenario: Unknown contract type returns 404
- **WHEN** a client requests `GET /contracts/does_not_exist/download/pdf`
- **THEN** the response status is 404
