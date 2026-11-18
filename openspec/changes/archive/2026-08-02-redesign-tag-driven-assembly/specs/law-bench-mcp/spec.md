## MODIFIED Requirements

### Requirement: Generate Contract from Tags
The `contract_generate` tool SHALL generate a contract deliverable for a given `contract_type` by delegating to `src.contracts.generate_contract`. When `stance` and/or `scenario` are supplied (directly or via `tags["stance"]` / `tags["scenario"]`), it SHALL delegate to `src.clauses.assemble.generate_contract_assembled`, which resolves the contract by **per-section override** with precedence `custom(stance) > tagged(scenario) > base(母版)`: assembly-ready `custom` clauses whose `tags.stance` matches the supplied `stance` override base/tagged in their section, `tagged` clauses whose `tags.scenario` matches the supplied `scenario` override base in their section, and `tagged`/`custom` clauses whose section is absent from the 母版 are extended into the contract. The assembled body SHALL contain exactly one clause body per section (no concatenation of multiple clause bodies within a section). The `tags` dict SHALL NOT recognize `region` or `province` - any such keys SHALL be ignored. It SHALL accept `format` (`docx` / `pdf` / `both`, default `pdf`) and `out_dir` (default `output/contracts`), write the deliverable(s) to disk, and return `{docx_path, pdf_path, slots, instructions, laws}` (unset formats map to `None`). A coherence-gate failure (missing canonical section, duplicate section, or an un-instructed slot) SHALL surface to the client as a tool error and no deliverable SHALL be written. An unknown `contract_type` SHALL surface to the client as a tool error. It SHALL be tagged `contracts`.

#### Scenario: Generate a PDF for a known contract type
- **WHEN** `contract_generate` is called with `contract_type="sale"`, `format="pdf"`
- **THEN** a `sale.pdf` is written under `output/contracts` and the result `pdf_path` points at it, `docx_path` is `None`, and `slots`/`instructions`/`laws` are populated

#### Scenario: Stance overrides base and tagged in matching sections
- **WHEN** `contract_generate` is called with `contract_type="employment"`, `stance="pro_a"`
- **THEN** for each section an assembly-ready `tags.stance="pro_a"` custom clause targets, the assembled body uses that custom clause body (overriding base and tagged); sections no custom clause targets retain their base (or tagged) clause body

#### Scenario: Scenario overrides base and extends absent sections
- **WHEN** `contract_generate` is called with `contract_type="sale"`, `tags={"scenario": "建材工业品"}`
- **THEN** for each section a `tags.scenario="建材工业品"` tagged clause targets, the assembled body uses that tagged clause body (overriding base); a tagged clause targeting a section absent from the 母版 is included as an extended section; sections no tagged clause targets retain their base clause body

#### Scenario: No clause concatenation within a section
- **WHEN** `contract_generate` is called with any combination of `scenario` and `stance` for a known type
- **THEN** every section heading in the assembled body is followed by exactly one clause body

#### Scenario: Coherence failure surfaces as an error
- **WHEN** the resolved contract has an un-instructed `{{slot}}` (or a missing canonical section / duplicate section)
- **THEN** the tool returns an error to the client naming the failing check and no deliverable file is written

#### Scenario: Region or province in tags is ignored
- **WHEN** `contract_generate` is called with `contract_type="sale"`, `tags={"region": "广东"}`
- **THEN** the `region` key is ignored (no province-based selection occurs) and the deliverable is generated as if no region were supplied

#### Scenario: Unknown contract type surfaces as an error
- **WHEN** `contract_generate` is called with `contract_type="not_a_real_type"`
- **THEN** the tool returns an error to the client (no file is written)
