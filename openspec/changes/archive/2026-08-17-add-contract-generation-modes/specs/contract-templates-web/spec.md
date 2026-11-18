# spec delta — contract-templates-web (MODIFIED)

## MODIFIED Requirements

### Requirement: Contract Detail Page
The system SHALL expose `GET /contracts/{contract_type}` returning HTML that shows, for the contract class: the rendered template content, each slot with its instruction (`label`, `description`, `example`, `required`), the per-type 法律法规 grouped by category, download links for the DOCX and PDF, **and a 「生成合同模板」 panel**. The panel SHALL present a mode selector (A 母版骨架 / B 标签组装 / C 存储 MinIO / D 批量组装 / E 自愈流水线 / F 自动拒绝 / G LLM 重生成), shared `stance` / `scenario` / `format` / `custom_clause_ids` inputs, a 「生成」 button, and a result area. The page SHALL return 404 for an unknown contract type.

#### Scenario: View a contract detail page
- **WHEN** a client requests `GET /contracts/sale`
- **THEN** the response is HTML containing the sale contract template, its slots with their instructions, its 法律法规, download links, and the generation-mode panel

#### Scenario: Unknown contract type returns 404
- **WHEN** a client requests `GET /contracts/does_not_exist`
- **THEN** the response status is 404

### Requirement: Download Generated Document
The system SHALL expose `GET /contracts/{contract_type}/download/{format}` that generates (if not already cached) and streams the contract's `.docx` (`format=docx`) or `.pdf` (`format=pdf`) using the same `src.contracts` generation API as the CLI. It SHALL return 404 for an unknown contract type and 400 for an unsupported format.

#### Scenario: Download a PDF
- **WHEN** a client requests `GET /contracts/sale/download/pdf` and a PDF backend is available
- **THEN** the response streams an `application/pdf` body with filename `sale.pdf`

#### Scenario: Unsupported format returns 400
- **WHEN** a client requests `GET /contracts/sale/download/rtf`
- **THEN** the response status is 400

#### Scenario: Unknown contract type returns 404
- **WHEN** a client requests `GET /contracts/does_not_exist/download/pdf`
- **THEN** the response status is 404

## ADDED Requirements

### Requirement: Generation-Mode Panel Behavior
The detail page's 「生成合同模板」 panel SHALL, on submit, POST the shared form to the route matching the selected mode (existing `/api/contracts/{type}/generate` for B, `/generate-stored` for C, new `/generate-batch` for D, `/pipeline` for E, `/auto-reject` for F, `/regenerate-template` for G; A links to the existing download buttons). For sync responses (B/C/D) it SHALL render the returned download/file URLs inline. For async responses (E/F/G, `202 + job_id`) it SHALL poll `GET /api/generation-jobs/{job_id}` until a terminal status and render the result or error. It SHALL require a confirm dialog before triggering write modes E, F, and G.

#### Scenario: Sync mode renders download links
- **WHEN** the user selects mode B and submits the panel
- **THEN** the panel POSTs to `/api/contracts/{type}/generate` and renders the returned `docx_url`/`pdf_url` as download links

#### Scenario: Async mode polls to completion
- **WHEN** the user selects mode E and confirms
- **THEN** the panel POSTs to `/api/contracts/{type}/pipeline`, receives `202 + job_id`, polls `/api/generation-jobs/{job_id}`, and on `completed` renders the result

#### Scenario: Write mode requires confirmation
- **WHEN** the user selects mode G and clicks 「生成」
- **THEN** a confirm dialog naming the global `contracts.json` rewrite is shown, and the request is sent only on confirmation
