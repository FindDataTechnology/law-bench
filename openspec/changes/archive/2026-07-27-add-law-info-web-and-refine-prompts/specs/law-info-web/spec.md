## ADDED Requirements

### Requirement: Law-Info Storage
The system SHALL store per-contract-type 法律法规 survey answers in a `law_info` table within the PostgreSQL database addressed by the `database_url` environment variable. Each row SHALL represent one (contract_type, source) pair with columns: `id` (BIGINT identity primary key), `contract_type` (TEXT, the type key e.g. `sale`), `source` (TEXT, `doubao` or `deepseek`), `zh_name` (TEXT, the Chinese contract-type name), `content` (TEXT, the markdown survey body), and `created_at` (TIMESTAMPTZ). The combination of (`contract_type`, `source`) SHALL be unique. The `law_info` table SHALL be created idempotently (`CREATE TABLE IF NOT EXISTS`) by the same schema source of truth that creates `rubrics`/`criteria`/`prompts` (`scripts/extract_harbor_rules.py`'s `SCHEMA`) and by `src/eval/store.py::ensure_schema`, so both the seeder path and the runtime/self-heal path establish it. `contract_type` SHALL be loosely coupled (no foreign key to `rubrics` or `prompts`), matching the existing contract-type discipline.

#### Scenario: The law_info table is created idempotently
- **WHEN** `create_schema` runs on a fresh database
- **THEN** the `law_info` table exists with all columns and the unique `(contract_type, source)` constraint
- **AND** re-running `create_schema` leaves it unchanged

#### Scenario: ensure_schema also creates the law_info table
- **WHEN** `src/eval/store.py::ensure_schema` runs on a fresh database
- **THEN** the `law_info` table exists
- **AND** the web runtime can query it without a separate migration step

#### Scenario: contract_type is loosely coupled
- **WHEN** a `law_info` row is inserted with `contract_type = sale`
- **THEN** no foreign key binds it to a `rubrics` or `prompts` row
- **AND** deleting the `contract_sale_v1` rubric does not invalidate the `law_info` row

### Requirement: Bundled Law-Info Markdown Seed Source
The system SHALL ship a bundled copy of the 82 law_info markdown files (41 contract types × {doubao, deepseek}) plus `contract_types.json` under `src/eval/seed/law_info/` (committed to the repository, because `output/` is gitignored and absent from the container). The bundled markdown SHALL be the canonical source of the survey content; the seeder SHALL read from it.

#### Scenario: Bundled files are present
- **WHEN** the repository is checked out
- **THEN** `src/eval/seed/law_info/doubao/<type>.md` and `src/eval/seed/law_info/deepseek/<type>.md` exist for each of the 41 contract type keys
- **AND** `src/eval/seed/law_info/contract_types.json` lists all 41 `{key, zh}` pairs

### Requirement: Idempotent Law-Info Seeding
The system SHALL provide `scripts/seed_law_info.py` that idempotently upserts the 82 law_info rows (one per `(contract_type, source)`) into the `law_info` table by reading the bundled markdown. Re-running the script SHALL NOT create duplicate rows and SHALL NOT modify any row in `rubrics`, `criteria`, `prompts`, or `eval_runs`. Upsert SHALL match on `(contract_type, source)`: UPDATE the content/zh_name if the pair exists, else INSERT. The seeder SHALL create the schema if absent.

#### Scenario: Seeding law_info is idempotent
- **WHEN** `seed_law_info.py` is run a second time
- **THEN** the `law_info` row count is unchanged (still 82)
- **AND** no duplicate rows are created
- **AND** the `rubrics`, `criteria`, `prompts`, and `eval_runs` row counts are unchanged

#### Scenario: Seeding populates both sources per type
- **WHEN** `seed_law_info.py` runs against a fresh database
- **THEN** for each of the 41 contract type keys there is one row with `source = doubao` and one with `source = deepseek`
- **AND** each row's `content` is the bundled markdown body and `zh_name` is the Chinese contract-type name from `contract_types.json`

#### Scenario: Seeding does not touch other tables
- **WHEN** `seed_law_info.py` runs after the prompt and rubric seeders have populated their rows
- **THEN** no prompt, rubric, criterion, or eval-run row is modified or deleted

### Requirement: Browse Law-Info Surveys
The system SHALL present a `GET /law-info` HTML page listing all 41 contract types (by Chinese name) with a link to a per-type detail page, and a `GET /law-info/{type}` HTML page showing that type's Doubao and DeepSeek survey answers side-by-side. Both pages SHALL be server-rendered with Jinja2 and SHALL read from the `law_info` table via `get_db()`. A missing or unknown `type` SHALL render a clear not-found state rather than raising. The type keys SHALL be the 41 keys from `contract_types.json`.

#### Scenario: List all contract types
- **WHEN** a user opens `/law-info`
- **THEN** all 41 contract types are listed by Chinese name with a link to `/law-info/<type>` for each

#### Scenario: Per-type detail shows both sources side-by-side
- **WHEN** a user opens `/law-info/sale`
- **THEN** the Doubao survey content and the DeepSeek survey content are both rendered on the same page, side-by-side
- **AND** each section is labeled with its source

#### Scenario: Unknown type renders not-found
- **WHEN** a user opens `/law_info/nonexistent_type`
- **THEN** the page renders a clear not-found state
- **AND** no unhandled exception is raised

### Requirement: Markdown Rendering of Law-Info Content
The system SHALL render `law_info.content` (markdown) to HTML server-side using `markdown-it-py` (promoted to a direct dependency in `pyproject.toml`). The rendered HTML SHALL be injected into the detail template. If rendering a given content body raises, the system SHALL fall back to presenting the raw markdown text escaped, so the page still renders. The content is first-party bundled (not user input at runtime), so default renderer options are acceptable.

#### Scenario: Markdown content is rendered to HTML
- **WHEN** the `/law-info/sale` page is rendered and the Doubao content contains markdown headings and lists
- **THEN** the Doubao section renders as structured HTML (headings, lists) rather than raw markdown text

#### Scenario: Render failure falls back to raw text
- **WHEN** a law_info content body cannot be rendered (renderer raises)
- **THEN** the section shows the raw markdown text, escaped
- **AND** the rest of the page still renders

### Requirement: Legal References Index Page
The system SHALL present a `GET /law-references` HTML page aggregating every unique 法律法规 mentioned across all 82 law_info answers, deduplicated by canonical name and categorized (`core_law` 核心法律, `judicial_interpretation` 司法解释, `special_statute` 专项法规, `procedural` 程序法, plus an `other` bucket for unmatched). Each entry SHALL list the `(contract_type, source)` pairs it appeared in. The page SHALL support filtering by source (doubao/deepseek) and by contract type. The aggregation SHALL be computed from the `law_info.content` rows in the database by a pure extractor function (`src/eval/legal_refs.py::extract_references`) so the index is always consistent with the seeded content.

#### Scenario: All referenced laws are listed
- **WHEN** a user opens `/law-references`
- **THEN** every law name appearing in any `law_info.content` row is listed exactly once (deduplicated)
- **AND** each entry is categorized and shows the contract types/sources it appeared in

#### Scenario: Filter by source
- **WHEN** a user filters `/law-references` to `source = doubao`
- **THEN** only laws appearing in at least one Doubao answer are shown

#### Scenario: Unmatched names are not dropped
- **WHEN** a law name in the content does not match a known categorization pattern
- **THEN** it is listed under the `other` bucket rather than omitted

### Requirement: Legal References Reference Document
The system SHALL provide `scripts/extract_legal_references.py` (a CLI) that reads the bundled law_info markdown (the canonical source) via the same `extract_references` function and writes a committed `docs/legal_references.md` containing the consolidated, deduplicated, categorized 法律法规 list. The document SHALL be regenerable so it stays in sync with the bundled markdown.

#### Scenario: The reference doc is generated
- **WHEN** `scripts/extract_legal_references.py` is run
- **THEN** `docs/legal_references.md` is written with every referenced law, deduplicated and categorized
- **AND** re-running produces an identical file (deterministic output)

#### Scenario: The doc reflects the bundled markdown
- **WHEN** a law name is added to a bundled markdown file and the script is re-run
- **THEN** the new law name appears in `docs/legal_references.md`
