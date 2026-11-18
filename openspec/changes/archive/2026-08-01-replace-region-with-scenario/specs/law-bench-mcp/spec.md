## MODIFIED Requirements

### Requirement: Generate Contract from Tags
The `generate_contract_from_tags` tool SHALL generate a contract deliverable for a given `contract_type` by delegating to `src.contracts.generate_contract`. When `stance` and/or `scenario` are supplied (directly or via `tags["stance"]` / `tags["scenario"]`), it SHALL delegate to `src.clauses.assemble.generate_contract_assembled` so the custom-clause selection is filtered by the supplied `stance` and the tagged-clause selection is filtered by the supplied `scenario` (业务场景). The `tags` dict SHALL NOT recognize `region` or `province` - any such keys SHALL be ignored. It SHALL accept `format` (`docx` / `pdf` / `both`, default `pdf`) and `out_dir` (default `output/contracts`), write the deliverable(s) to disk, and return `{docx_path, pdf_path, slots, instructions, laws}` (unset formats map to `None`). An unknown `contract_type` SHALL surface to the client as a tool error.

#### Scenario: Generate a PDF for a known contract type
- **WHEN** `generate_contract_from_tags` is called with `contract_type="sale"`, `format="pdf"`
- **THEN** a `sale.pdf` is written under `output/contracts` and the result `pdf_path` points at it, `docx_path` is `None`, and `slots`/`instructions`/`laws` are populated

#### Scenario: Stance filter is applied to assembled custom clauses
- **WHEN** `generate_contract_from_tags` is called with `contract_type="employment"`, `stance="pro_a"`
- **THEN** the assembled contract body includes only custom clauses whose `tags.stance = "pro_a"` (base and tagged clauses unchanged)

#### Scenario: Scenario filter is applied to assembled tagged clauses
- **WHEN** `generate_contract_from_tags` is called with `contract_type="sale"`, `tags={"scenario": "建材工业品"}`
- **THEN** the assembled contract body includes `source=tagged` clauses whose `tags.scenario = "建材工业品"` (base and custom clauses follow their respective rules)

#### Scenario: Region or province in tags is ignored
- **WHEN** `generate_contract_from_tags` is called with `contract_type="sale"`, `tags={"region": "广东"}`
- **THEN** the `region` key is ignored (no province-based selection occurs) and the deliverable is generated as if no region were supplied

#### Scenario: Unknown contract type surfaces as an error
- **WHEN** `generate_contract_from_tags` is called with `contract_type="not_a_real_type"`
- **THEN** the tool returns an error to the client (no file is written)
