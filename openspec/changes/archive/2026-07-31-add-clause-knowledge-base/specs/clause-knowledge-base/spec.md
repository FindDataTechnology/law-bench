## ADDED Requirements

### Requirement: Contract Corpus Reader
The system SHALL read the 示范文本 corpus from MinIO (`scraw-law-contracts/contracts/`) without depending on Elasticsearch or `llama-index-readers-file`. `list_corpus_documents(prefix="contracts/")` SHALL return a list of `{object_name, source_path, ext}` for every `.docx`/`.pdf` object under the prefix. `read_document(object_name)` SHALL download the object and return `{source_path, ext, text}` by parsing `.docx` with `python-docx` and `.pdf` with `pypdf`. When a `.docx` and `.pdf` share a UUID stem, the `.docx` SHALL be preferred.

#### Scenario: List corpus documents
- **WHEN** `list_corpus_documents()` is called and MinIO is reachable
- **THEN** it returns an entry for every `.docx`/`.pdf` object under `scraw-law-contracts/contracts/`, each with a `source_path` like `scraw-law-contracts/contracts/1/<uuid>.docx`

#### Scenario: Parse a docx contract to text
- **WHEN** `read_document("<uuid>.docx")` is called for a contract in the corpus
- **THEN** it returns a `text` string containing the contract's paragraph content (non-empty)

#### Scenario: MinIO unreachable degrades gracefully
- **WHEN** `list_corpus_documents()` is called and MinIO cannot be reached
- **THEN** it raises a clear `ConfigError`/connection error (it SHALL NOT silently return an empty list)

### Requirement: Clause Extraction Pipeline
The system SHALL extract structured clauses from each corpus document via the LLM. `extract_clauses(document)` SHALL return a list of clauses, each `{contract_type, section, body, slot_instructions, law_refs, province, level, source_path}`. `contract_type` SHALL be one of the 41 keys from `list_contract_types()` or `"unknown"`. `body` SHALL be contract clause text that MAY contain `{{slot}}` placeholders. `slot_instructions` SHALL be a list of `{name, label, description, example, required}` for every `{{slot}}` in `body`. `law_refs` SHALL be a list of `{name, category, category_zh}` for the 《...》 provisions the clause relies on. Extraction SHALL be idempotent: re-running a document deletes its existing clauses (keyed by `source_path` + `section` + `body_hash`) then re-inserts.

#### Scenario: Extract clauses from a document
- **WHEN** `extract_clauses(document)` is called for a parsed contract
- **THEN** it returns a non-empty list of clauses, each with a `section`, a non-empty `body`, a `contract_type` that is either a valid contract-type key or `"unknown"`, and `slot_instructions` covering every `{{slot}}` in `body`

#### Scenario: Slot instructions cover clause slots
- **WHEN** a clause's `body` contains `{{property_name}}` and `{{party_a}}`
- **THEN** its `slot_instructions` contains an entry for `property_name` and an entry for `party_a`, each with a non-empty `description`

#### Scenario: Idempotent re-extraction
- **WHEN** `extract_clauses(document)` is run twice for the same document
- **THEN** the `clauses` table contains exactly one row per `(source_path, section, body_hash)` - no duplicates

### Requirement: Clause Knowledge Base Storage
The system SHALL store clauses in a Postgres `clauses` table with a `category` column taking one of `base`, `tagged`, `custom`. `base` clauses come from national-level 示范文本 (per `contract_type`). `tagged` clauses come from provincial 示范文本 and SHALL have a non-null `province`. `custom` clauses are user-authored and SHALL have a null `source_path`. `list_clauses(contract_type, *, category=None, province=None)` SHALL return matching clauses ordered by canonical section order. `upsert_clause(clause)` and `delete_clauses(source_path)` SHALL maintain idempotency. The schema SHALL be created idempotently by `ensure_schema`.

#### Scenario: Store and retrieve base clauses
- **WHEN** a base clause for `property_service` is upserted, then `list_clauses("property_service", category="base")` is called
- **THEN** the clause is returned with `category="base"`, `level="national"`, and `province` null or the national marker

#### Scenario: Tagged clauses carry a province
- **WHEN** `list_clauses("property_service", category="tagged", province="吉林")` is called
- **THEN** every returned clause has `category="tagged"`, a non-null `province` of `"吉林"`, and `level="local"`

#### Scenario: Custom clauses have no source path
- **WHEN** a user-authored clause is upserted with `category="custom"`
- **THEN** its `source_path` is null and it is returned by `list_clauses(<type>, category="custom")`

### Requirement: Province and Level Inference
The system SHALL infer `province` and `level` from contract content (not from the MinIO path). `level` SHALL be `"national"` when the document has no provincial issuing authority and references only national-level laws; otherwise `level` SHALL be `"local"` with `province` set to the inferred province. When province is ambiguous, `level` SHALL default to `"national"` with `province` null. The MinIO `1/`..`5/`/`None/` top-level directories SHALL NOT be interpreted as province or contract-type labels.

#### Scenario: Provincial contract is labeled with its province
- **WHEN** a contract titled "吉林省前期物业服务合同" issued by 吉林省住建厅 and citing 《吉林省物业管理条例》 is extracted
- **THEN** its clauses have `level="local"` and `province="吉林"`

#### Scenario: National contract is labeled national
- **WHEN** a contract with no provincial issuing authority and only national-level law references is extracted
- **THEN** its clauses have `level="national"` and `province` null

#### Scenario: MinIO dirs are not used as labels
- **WHEN** a 吉林省 contract stored under `contracts/1/` is extracted
- **THEN** `province` is `"吉林"` (inferred from content), not derived from the `1/` directory

### Requirement: Clause-Assembled Contract Generation
The system SHALL assemble a contract from base + provincial-tagged + custom clauses. `generate_contract_assembled(contract_type, *, province=None, custom_clause_ids=None, format="pdf", out_dir=None)` SHALL select base clauses for the type, tagged clauses for the type and `province` (when given), and the listed custom clauses; order them by a canonical `SECTION_ORDER`; concatenate their bodies into one Markdown body; and render it to `.docx`/`.pdf` via `document-generation` with every `{{slot}}` left as a highlighted, fillable placeholder (no slot pre-filled). It SHALL return `{docx_path, pdf_path, slots, instructions, law_refs}` where `instructions` is the union of the 12 canonical `SlotInstruction`s plus any clause-declared slots, and `law_refs` is the deduped union. The existing skeleton `generate_contract` SHALL remain unchanged as the default path. It SHALL raise `NotFoundError` for an unknown contract type.

#### Scenario: Assemble a contract for a province
- **WHEN** `generate_contract_assembled("property_service", province="吉林", format="pdf")` is called and a PDF backend is available
- **THEN** a `.pdf` is written under `output/contracts` whose body includes the base clauses for `property_service` and the 吉林 tagged clauses, in canonical section order, with `{{slot}}` placeholders rendered as highlighted fillable placeholders

#### Scenario: Slots stay fillable
- **WHEN** an assembled contract is generated in any format
- **THEN** no `{{slot}}` is pre-filled; every slot appears as a highlighted placeholder

#### Scenario: Instructions cover canonical and clause-declared slots
- **WHEN** `generate_contract_assembled("property_service", province="吉林")` returns `instructions`
- **THEN** it includes the 12 canonical slots (e.g. `party_a`, `subject`) and any clause-declared slots (e.g. `property_name`), each with a non-empty `description`

#### Scenario: Unknown contract type raises
- **WHEN** `generate_contract_assembled("does_not_exist")` is called
- **THEN** `NotFoundError` is raised

### Requirement: Command-Line Tool
The system SHALL expose a CLI `python -m src.clauses`. `python -m src.clauses extract [--limit N] [--force]` SHALL run resumable corpus extraction (skipping already-extracted `source_path`s unless `--force`). `python -m src.clauses generate <contract_type> [--province <省>] [--custom <id,...>] [--format pdf|docx|both]` SHALL assemble and generate, printing the output path(s). On success it SHALL exit 0; on `NotFoundError` it SHALL exit non-zero with an error naming the type.

#### Scenario: Resumable extraction
- **WHEN** `python -m src.clauses extract --limit 20` is run twice
- **THEN** the second run skips documents already extracted (unless `--force`)

#### Scenario: Generate an assembled contract via CLI
- **WHEN** `python -m src.clauses generate property_service --province 吉林 --format pdf` is run and a PDF backend is available
- **THEN** it exits 0 and prints the path to the generated PDF

#### Scenario: Unknown contract type via CLI
- **WHEN** `python -m src.clauses generate does_not_exist` is run
- **THEN** it exits non-zero with an error naming the unknown type

### Requirement: Web Exposure
The system SHALL expose the clause knowledge base on the web. `GET /clauses` SHALL list clauses browsable by contract type, category, and province. `GET /clauses/extract` SHALL trigger resumable extraction. `GET /clauses/{type}/generate?province=...&format=...` SHALL assemble and stream the generated `.docx`/`.pdf`. Routes SHALL be wired into `src/web/app.py` alongside the existing `contracts` router, and a `/clauses` nav link SHALL be added.

#### Scenario: Browse clauses
- **WHEN** `GET /clauses` is requested
- **THEN** it returns a page listing clauses grouped by contract type, with category and province filters

#### Scenario: Generate and download an assembled contract
- **WHEN** `GET /clauses/property_service/generate?province=吉林&format=docx` is requested
- **THEN** it streams a `.docx` assembled from base + 吉林 tagged clauses

#### Scenario: Unknown contract type on the web
- **WHEN** `GET /clauses/does_not_exist/generate` is requested
- **THEN** it returns 404
