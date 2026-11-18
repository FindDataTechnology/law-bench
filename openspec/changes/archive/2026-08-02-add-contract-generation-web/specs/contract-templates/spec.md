## ADDED Requirements

### Requirement: Available Contract Classes
The system SHALL expose the supported contract classes from `output/law_info/contract_types.json`. `list_contract_types()` SHALL return a list of `{key, zh}` objects in file order.

#### Scenario: List contract classes
- **WHEN** `list_contract_types()` is called
- **THEN** it returns 41 entries each with a `key` (e.g. `"sale"`) and a `zh` (e.g. `"买卖合同"`) in the order they appear in `contract_types.json`

### Requirement: Contract Template per Contract Class
The system SHALL provide a contract template for each contract class. A template is Markdown content containing `{{slot_name}}` placeholders conforming to the `document-generation` slot token model. `get_template(contract_type)` SHALL return `{type, zh_name, body, slots}` where `slots` is the de-duplicated list of slot names found in `body` in first-appearance order. It SHALL raise `NotFoundError` for an unknown contract type.

#### Scenario: Retrieve a contract template
- **WHEN** `get_template("sale")` is called
- **THEN** it returns an object whose `type` is `"sale"`, `zh_name` is `"买卖合同"`, `body` is non-empty Markdown, and `slots` is the de-duplicated slot names present in `body`

#### Scenario: Unknown contract type raises
- **WHEN** `get_template("does_not_exist")` is called
- **THEN** `NotFoundError` is raised

### Requirement: Slot Instruction Manifest
The system SHALL provide a slot-instruction manifest for each contract class mapping every slot in the template to structured guidance. `get_slot_instructions(contract_type)` SHALL return a list of `{name, label, description, example, required}` objects. Every slot name returned by `get_template(contract_type)["slots"]` SHALL have exactly one matching instruction entry (matched by `name`); no instruction SHALL reference a slot absent from the template.

#### Scenario: Every slot has an instruction
- **WHEN** `get_template("sale")["slots"]` and `get_slot_instructions("sale")` are called
- **THEN** the set of instruction `name` values equals the set of template `slots`

#### Scenario: Instruction fields are populated
- **WHEN** `get_slot_instructions("sale")` is called
- **THEN** each entry has a non-empty `label` (中文), a non-empty `description`, an `example`, and a boolean `required`

### Requirement: Per-Contract-Class Legal Regulation Extraction
The system SHALL extract the 法律法规 for a contract class from the Doubao+DeepSeek answers by reusing `src.eval.legal_refs.extract_references`. `extract_laws_for_type(contract_type)` SHALL return a list of `{name, category, category_zh, sources}` for the laws referenced in that contract class's answers, sorted by category order then name. `sources` SHALL list which of `doubao`/`deepseek` cited the law. It SHALL raise `NotFoundError` for an unknown contract type.

#### Scenario: Extract laws for a contract class
- **WHEN** `extract_laws_for_type("sale")` is called
- **THEN** it returns a non-empty list whose entries each have a `name` (a law cited in `《》`), a `category` in `CATEGORY_ORDER`, a `category_zh`, and a `sources` list containing `"doubao"` and/or `"deepseek"`

#### Scenario: Unknown contract type raises
- **WHEN** `extract_laws_for_type("does_not_exist")` is called
- **THEN** `NotFoundError` is raised

### Requirement: Contract DOCX and PDF Generation
The system SHALL generate a `.docx` and/or `.pdf` for a contract class from its template via the `document-generation` module (`create_docx`, `docx_to_pdf`), with every slot rendered as a highlighted, fillable placeholder (no slot pre-filled). `generate_contract(contract_type, *, format="pdf", out_dir=None)` SHALL write the requested format(s) under `out_dir` (default `output/contracts`) and return `{docx_path, pdf_path, slots, instructions, laws}` where formats not requested map to `None`. It SHALL raise `NotFoundError` for an unknown contract type.

#### Scenario: Generate a PDF for a contract class
- **WHEN** `generate_contract("sale", format="pdf")` is called and a PDF backend is available
- **THEN** a `.pdf` file is written under `output/contracts/sale.pdf`
- **THEN** the returned `pdf_path` points to that file, `docx_path` is `None`, and `slots`/`instructions`/`laws` are populated

#### Scenario: Generate both DOCX and PDF
- **WHEN** `generate_contract("sale", format="both")` is called and a PDF backend is available
- **THEN** both `output/contracts/sale.docx` and `output/contracts/sale.pdf` exist and are returned in `docx_path`/`pdf_path`

#### Scenario: Generated DOCX contains highlighted slots
- **WHEN** `generate_contract("sale", format="docx")` is called and the resulting document is inspected
- **THEN** the document contains the template's `{{slot}}` tokens rendered as highlighted placeholders with no slot pre-filled

### Requirement: Command-Line Tool
The system SHALL expose a CLI `python -m src.contracts` that extracts the laws, builds the template and slot instructions, and generates the requested format(s) for one contract class or all classes. `python -m src.contracts <contract_type> [--format pdf|docx|both] [--out DIR]` SHALL generate for a single type; `--all` SHALL iterate every contract class. On success it SHALL print the generated file path(s).

#### Scenario: Generate a single contract via CLI
- **WHEN** `python -m src.contracts sale --format pdf` is run and a PDF backend is available
- **THEN** it exits 0 and prints the path to `output/contracts/sale.pdf`

#### Scenario: Generate all contracts via CLI
- **WHEN** `python -m src.contracts --all --format docx` is run
- **THEN** it exits 0 and generates a `.docx` for every contract class

#### Scenario: Unknown contract type via CLI
- **WHEN** `python -m src.contracts does_not_exist` is run
- **THEN** it exits non-zero with an error message naming the unknown type
