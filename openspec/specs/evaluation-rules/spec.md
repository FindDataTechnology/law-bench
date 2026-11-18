# evaluation-rules Specification

## Purpose
Store rubrics and criteria with Harbor provenance, support local rubric extension, provide per-class Chinese contract rubrics, and group compare runs with their eval_run linkage.

## Requirements

### Requirement: Rubric and Criterion Storage

The system SHALL store evaluation rubrics and their criteria in a PostgreSQL database addressed by the `database_url` environment variable. Each rubric SHALL have a name, context, source, source_path, and description. Each criterion SHALL belong to exactly one rubric and SHALL have a name, description, guidance, and ordinal. The combination of rubric and criterion name SHALL be unique.

**This change adds domain ownership**: each rubric SHALL belong to exactly one domain (`domain_id`); a rubric with no domain SHALL NOT be creatable. Rubrics SHALL be inheritable: a child domain SHALL see its parent domain's rubrics as effective (read-only) standards, and MAY fork one, in which case the fork SHALL record the parent rubric it derives from plus a human-readable difference summary. Scoring and run statistics SHALL be attributed to the domain that owns the rubric used.

#### Scenario: Store a harbor rubric with its criteria
- **WHEN** the extraction script runs against harbor's `default-rubric.toml` for the legal domain
- **THEN** a `task_quality` rubric row is stored with `source = harbor:v0.20.0`, `context = check`, `domain_id` = the legal domain, and `source_path` pointing at the harbor TOML file
- **AND** each of its 11 criteria is stored with name, description, and guidance

#### Scenario: Query criteria of a rubric
- **WHEN** a caller queries criteria by rubric name within a domain
- **THEN** all criteria for that rubric are returned ordered by `ordinal`

#### Scenario: 子域继承父域 rubric
- **WHEN** 子域 `legal/contract-review` 查看可用评测标准
- **THEN** 父域 `legal` 的 rubric 出现在「继承自父域」分组中，可用但不可在本域编辑

#### Scenario: fork 必须留差异
- **WHEN** 子域对某父域 rubric 发起 fork 并修改了其中 2 条判据
- **THEN** 新 rubric 记录 `derived_from` 指向父域 rubric，并保存本次差异摘要（哪几条判据被改、改成什么）

### Requirement: Harbor Provenance and Idempotent Extraction
The system SHALL extract harbor's rubrics from the installed harbor package's TOML rubric files when harbor is installed, recording their provenance (`source`, `source_path`, `context`) and the installed harbor version. When the harbor package cannot be located on disk, the system SHALL fall back to a bundled seed copy of harbor's rubric TOMLs shipped in the repository, recording `source = harbor:v0.20.0`. Re-running the extraction SHALL be idempotent: it SHALL NOT create duplicate rubrics or criteria, and SHALL NOT modify or delete rows whose `source` is not `harbor`.

#### Scenario: Re-run extraction does not duplicate
- **WHEN** the extraction script is run a second time
- **THEN** the rubric and criteria row counts are unchanged
- **AND** no duplicate rows are created

#### Scenario: Local rows are preserved across re-extraction
- **WHEN** a local contract rubric exists (`source = local`) and the extraction script runs
- **THEN** the local rubric and its criteria remain unchanged

#### Scenario: Harbor not installed falls back to the bundled seed
- **WHEN** the harbor package cannot be located on disk
- **THEN** the extraction script loads harbor rubrics from the bundled seed TOMLs shipped in the repository
- **AND** exits 0, recording `source = harbor:v0.20.0`
- **AND** does not raise an error requiring harbor to be installed

### Requirement: Extensibility for Local Rubrics
The schema SHALL support locally-authored rubrics distinct from harbor reference rubrics, identified by `source = local`. Local rubrics SHALL coexist with harbor rubrics in the same tables without conflict.

#### Scenario: Add a local contract rubric
- **WHEN** a local rubric is inserted with `source = local` and `context = contract`
- **THEN** it is stored alongside harbor rubrics
- **AND** it is not affected by subsequent harbor extractions

### Requirement: Per-Class Chinese Contract Rubrics
The system SHALL support an idempotently-seeded set of per-class Chinese contract rubrics - one per 民法典 typical named contract type (买卖合同, 供用电水气热力, 赠与合同, 借款合同, 保证合同, 租赁合同, 融资租赁, 保理合同, 承揽合同, 建设工程, 运输合同, 技术合同, 保管合同, 仓储合同, 委托合同, 物业服务, 行纪合同, 中介合同, 合伙合同). Each SHALL be stored with `source = local` and `context = contract`, named `contract_<type>_v1`, and SHALL consist of the shared base criteria (party identification, governing law, clause completeness, legal citation accuracy) plus 4-6 type-specific Chinese criteria drawn from that type's 民法典 mandatory-clause set. The seeding script (`scripts/seed_contract_rubrics.py`) SHALL be idempotent and SHALL NOT modify or delete any row whose `source` is not `local`.

#### Scenario: Seed the 19 per-class rubrics
- **WHEN** `seed_contract_rubrics.py` runs against a database with only the harbor rubrics and `contract_drafting_v1`
- **THEN** 19 new `contract_<type>_v1` rubrics are inserted with `source = local` and `context = contract`
- **AND** each rubric has the 4 shared base criteria plus its 4-6 type-specific criteria

#### Scenario: Re-seeding per-class rubrics is idempotent
- **WHEN** `seed_contract_rubrics.py` is run a second time
- **THEN** the rubric and criteria row counts are unchanged
- **AND** no duplicate rubric or criterion rows are created

#### Scenario: Per-class rubrics coexist with harbor rubrics
- **WHEN** the 19 per-class local rubrics exist alongside the harbor rubrics
- **THEN** both are stored in the same `rubrics`/`criteria` tables without conflict
- **AND** subsequent harbor re-extraction leaves the per-class local rubrics unchanged

### Requirement: Compare Runs Grouping Table
The system SHALL add a `compare_runs` table to the PostgreSQL database addressed by `database_url`, created idempotently by `src/eval/store.py::ensure_schema` (alongside `eval_runs` and `eval_criteria_results`). Columns: `id` primary key, `label`, `contract_type`, `rubric_name`, `task_desc`, `gen_mode`, `n_drafts`, `created_at`. One `compare_runs` row groups the `eval_runs` rows that belong to a single compare via the `eval_runs.compare_run_id` snapshot column.

#### Scenario: The compare_runs table is created idempotently
- **WHEN** `ensure_schema` runs on a fresh database
- **THEN** the `compare_runs` table exists with all columns
- **AND** re-running `ensure_schema` leaves it unchanged

### Requirement: Compare-Driven Columns on eval_runs
The system SHALL add nullable, snapshotted columns to `eval_runs`: `compare_run_id` (INTEGER, soft reference to `compare_runs.id`, no FK constraint), `prompt_name` (TEXT), `prompt_type` (TEXT), `variant_label` (TEXT), and `draft_text` (TEXT). Existing standalone (non-compare) runs SHALL continue to work with these columns null. No FK constraint SHALL be introduced, so a run survives deletion of its prompt or compare (snapshot discipline).

#### Scenario: Standalone runs keep working
- **WHEN** `src/eval/run.py` stores a standalone eval run after migration
- **THEN** the run is stored with `compare_run_id`, `prompt_name`, `prompt_type`, `variant_label`, and `draft_text` all null
- **AND** `--list-runs` output is unchanged

#### Scenario: A compare run records its prompt and draft
- **WHEN** a compare stores an `eval_runs` row
- **THEN** `compare_run_id`, `prompt_name`, `prompt_type`, `variant_label`, and `draft_text` are populated from the prompt and draft used
- **AND** renaming or deleting the prompt afterward does not change the stored row

### Requirement: Idempotent Additive-Column Migration
The system SHALL migrate existing databases to the new schema via a guarded `ALTER TABLE … ADD COLUMN IF NOT EXISTS` helper invoked from `ensure_schema`, checking `information_schema.columns` before each add. The migration SHALL run on every startup, SHALL be idempotent (a no-op once columns exist), and SHALL NOT touch any existing row's data (new columns default to null).

#### Scenario: An existing DB is migrated on startup
- **WHEN** `ensure_schema` runs against a DB that predates this change
- **THEN** `prompt_type` is added to `prompts`, `compare_runs` is created, and the five new columns are added to `eval_runs`
- **AND** existing `eval_runs` and `prompts` rows have null/blank new columns

#### Scenario: Migration is idempotent
- **WHEN** `ensure_schema` runs a second time
- **THEN** no `ALTER TABLE` is attempted for columns that already exist
- **AND** no error is raised

### Requirement: Bundled Harbor Rubric Seed and Startup Self-Heal
The system SHALL ship a bundled copy of harbor's rubric TOMLs (`task_quality` with 11 criteria, `trial_behavior` with 2 criteria) in the repository, pinned to harbor v0.20.0. The system SHALL provide an importable seeding entrypoint that idempotently ensures harbor rubrics are present in a target database: it SHALL create the schema if absent and upsert every harbor rubric from the installed harbor package when available, otherwise from the bundled seed. The heal SHALL be scoped to rows whose `source` is `harbor` (`source LIKE 'harbor:%'`); it SHALL NOT modify or delete local rubrics, prompts, or evaluation-run data. The container SHALL run this heal on every startup before serving requests, so a stale or partially-seeded database self-heals without a volume reset or rebuild.

#### Scenario: Empty database is healed
- **WHEN** the seeding entrypoint runs against a database with no `rubrics` table
- **THEN** the schema is created and the two harbor rubrics are present with 13 total criteria
- **AND** each harbor rubric has `source = harbor:v0.20.0`

#### Scenario: Stale volume self-heals on container startup
- **WHEN** the container starts with a volume whose database has local rubrics but no harbor rubrics
- **THEN** the startup heal inserts the two harbor rubrics and their 13 criteria
- **AND** the existing local rubrics and any evaluation-run rows remain unchanged

#### Scenario: Heal is idempotent
- **WHEN** the seeding entrypoint runs a second time against an already-healed database
- **THEN** the harbor rubric and criteria counts are unchanged
- **AND** no duplicate rows are created

#### Scenario: Installed harbor takes precedence over the bundle
- **WHEN** the harbor package is installed and the seeding entrypoint runs
- **THEN** criteria are loaded from the installed harbor package
- **AND** `source` records the installed harbor's version

#### Scenario: Re-extract harbor button works without harbor installed
- **WHEN** the "Re-extract harbor" control is triggered in a container where harbor is not installed
- **THEN** the request succeeds (exit 0) by loading from the bundled seed
- **AND** the refreshed rubric list is returned

### Requirement: Practical Contract Type Rubrics
The system SHALL support a second idempotently-seeded set of per-class Chinese contract rubrics covering practical (中国合同分类法 Part 2) contract types that are not already covered by the 民法典 typical named contract types. The seeded set SHALL comprise these 22 non-overlapping practical types: `company_formation`, `equity_transfer`, `capital_increase`, `merger_acquisition`, `equity_incentive`, `vam_agreement`, `equity_holding_in_trust` (门类 A - 公司股权); `real_estate_sale`, `real_estate_lease`, `employment`, `labor_dispatch`, `ip_license`, `franchise` (门类 B - 常见法律关系); `real_estate_development`, `insurance`, `trust`, `private_equity_fund`, `software_development`, `film_production`, `talent_agency`, `ppp_project`, `tourism_service` (门类 C - 特定行业). Each SHALL be stored with `source = local` and `context = contract`, named `contract_<type>_v1`, and SHALL consist of the same 4 shared base criteria (party identification, governing law, clause completeness, legal citation accuracy) plus 4-6 type-specific Chinese criteria drawn from that type's governing statute beyond 民法典 (e.g. 公司法, 劳动法/劳动合同法, 保险法, 信托法, 城市房地产管理法, 商业特许经营管理条例, 旅游法). The seeding script (`scripts/seed_contract_rubrics.py`) SHALL seed both the 民法典 set and this practical set in one idempotent pass, SHALL NOT modify or delete any row whose `source` is not `local`, and SHALL NOT seed a practical type that 1:1 duplicates a 民法典 type.

#### Scenario: Seed the 22 practical-type rubrics
- **WHEN** `seed_contract_rubrics.py` runs against a database that already has the harbor rubrics, the 19 民法典 per-class rubrics, and `contract_drafting_v1`
- **THEN** 22 new `contract_<type>_v1` rubrics are inserted with `source = local` and `context = contract`
- **AND** each practical rubric has the 4 shared base criteria plus its 4-6 type-specific criteria
- **AND** the 19 民法典 rubrics, the sample rubric, and the harbor rubrics are unchanged

#### Scenario: Re-seeding practical-type rubrics is idempotent
- **WHEN** `seed_contract_rubrics.py` is run a second time
- **THEN** the rubric and criteria row counts are unchanged
- **AND** no duplicate rubric or criterion rows are created

#### Scenario: Practical rubrics do not duplicate 民法典 types
- **WHEN** the seeded practical types are enumerated
- **THEN** none of them is a 1:1 duplicate of a 民法典 typical named contract type (no second rubric for 买卖/租赁/借款/担保/委托/建设工程/运输/保管/仓储/融资租赁/合伙)
- **AND** the borderline types `real_estate_sale`, `real_estate_lease`, and `software_development` are seeded as distinct types because their governing statute and mandatory clauses differ from the generic 民法典 rubric

#### Scenario: Practical rubrics coexist with all other rows
- **WHEN** the 22 practical local rubrics exist alongside the 民法典 rubrics, the sample rubric, and the harbor rubrics
- **THEN** all are stored in the same `rubrics`/`criteria` tables without conflict
- **AND** subsequent harbor re-extraction leaves every local rubric (民法典 + practical + sample) unchanged

### Requirement: Postgres Connection and Schema Management
The system SHALL obtain a PostgreSQL connection from the `database_url` environment variable (a libpq DSN, e.g. `postgresql://user:pass@host:5432/db`). The web layer SHALL resolve the active connection via the `get_db()` dependency seam, which SHALL no longer return a filesystem `Path`. Schema creation for `rubrics`, `criteria`, `prompts`, `eval_runs`, `eval_criteria_results`, and `compare_runs` SHALL be idempotent (`CREATE TABLE IF NOT EXISTS`), SHALL enforce foreign keys with `ON DELETE CASCADE` where the prior SQLite schema did, and SHALL use `BIGINT GENERATED ALWAYS AS IDENTITY` for auto-increment primary keys. Insert paths SHALL obtain generated primary keys via `RETURNING id`.

#### Scenario: get_db returns a connection from database_url
- **WHEN** a request handler depends on `get_db()`
- **THEN** it receives a live PostgreSQL connection resolved from `database_url`
- **AND** no filesystem path is involved in resolving the database

#### Scenario: Schema is created idempotently with FK cascade
- **WHEN** `ensure_schema` runs on a fresh PostgreSQL database
- **THEN** all six tables are created with identity primary keys
- **AND** deleting a rubric cascades to its criteria via the `ON DELETE CASCADE` foreign key

#### Scenario: Generated ids are obtained via RETURNING
- **WHEN** a rubric or prompt is inserted
- **THEN** the new row's generated `id` is returned from the same statement via `RETURNING id`
- **AND** no separate `lastrowid` lookup is used

### Requirement: Law-Refined Variant Contract Rubrics
The system SHALL seed a second set of per-class Chinese contract rubrics - the **law-refined** variants - one per contract type key (the same 41 keys covered by the v1 rubrics: 19 民法典 types + 22 practical types). Each SHALL be named `contract_<type>_v2`, stored with `source = local` and `context = contract`, and SHALL consist of the 4 shared base criteria (party identification, governing law, clause completeness, legal citation accuracy) plus 4-6 type-specific Chinese criteria whose `guidance` references the correct governing statutes and judicial interpretations for that type as surfaced by the law_info survey (e.g. for `sale`: citing 《最高人民法院关于审理买卖合同纠纷案件适用法律问题的解释》法释〔2020〕17号 and the 民法典 595–647条 range; for `employment`: citing 《劳动合同法》; for `insurance`: citing 《保险法》). The seeding script (`scripts/seed_contract_rubrics.py`) SHALL seed the v1 rubrics AND these `contract_<type>_v2` rubrics in one idempotent pass, SHALL NOT modify any v1 `contract_<type>_v1` row (upsert matches by name; the names differ), and SHALL NOT modify or delete any row whose `source` is not `local`.

#### Scenario: Seed the 41 law-refined variant rubrics
- **WHEN** `seed_contract_rubrics.py` runs against a database that already has the 41 v1 `contract_<type>_v1` rubrics
- **THEN** 41 new `contract_<type>_v2` rubrics are inserted with `source = local` and `context = contract`
- **AND** each v2 rubric has the 4 shared base criteria plus its 4-6 type-specific criteria whose guidance cites the correct governing statutes from the law_info survey
- **AND** the 41 v1 rubrics are unchanged

#### Scenario: Re-seeding law-refined rubrics is idempotent
- **WHEN** `seed_contract_rubrics.py` is run a second time
- **THEN** the rubric and criteria row counts are unchanged
- **AND** no duplicate rubric or criterion rows are created

#### Scenario: v1 rubrics are not modified by the v2 seed
- **WHEN** `seed_contract_rubrics.py` runs after the v2 rubrics already exist
- **THEN** every v1 `contract_<type>_v1` rubric and its criteria retain their original content
- **AND** no v1 row is overwritten by the seeder

#### Scenario: v2 rubrics coexist with v1 and harbor rubrics
- **WHEN** the 41 v2 rubrics exist alongside the 41 v1 rubrics, the sample rubric, and the harbor rubrics
- **THEN** all are stored in the same `rubrics`/`criteria` tables without conflict
- **AND** subsequent harbor re-extraction leaves every local rubric (v1 + v2 + sample) unchanged

#### Scenario: v2 rubric criteria cite accurate statutes
- **WHEN** the `contract_sale_v2` rubric's type-specific criteria are inspected
- **THEN** at least one criterion's guidance references the 买卖合同 judicial interpretation (法释〔2020〕17号) or the 民法典 595–647条 range
- **AND** no criterion cites a fabricated or repealed statute as currently in force

### Requirement: Layered Judgment Mechanism for Common Criteria
The system SHALL replace binary judgment (PASS/FAIL) with layered judgment (PASS/HALF_PASS/FAIL) for common criteria. Layered judgment allows the system to distinguish between "fully compliant", "partially compliant", and "non-compliant" states.

#### Scenario: Apply layered judgment to governing_law_present
- **WHEN** evaluating the governing_law_present criterion
- **THEN** the system SHALL apply layered judgment:
  - PASS if a dedicated "Applicable Law" clause explicitly states the governing jurisdiction
  - HALF_PASS if legal references appear in "Recitals" or "Dispute Resolution" sections
  - FAIL if no legal references are present anywhere in the contract
- **AND** record the judgment level in the evaluation results

#### Scenario: Apply layered judgment to legal_citation_accuracy
- **WHEN** evaluating the legal_citation_accuracy criterion
- **THEN** the system SHALL apply layered judgment:
  - PASS if law names and article numbers are accurate and current
  - HALF_PASS if law names are accurate but article numbers are missing or imprecise
  - FAIL if law names are fabricated or repealed
- **AND** provide specific feedback on citation accuracy

#### Scenario: Apply layered judgment to legal_basis_citation
- **WHEN** evaluating the legal_basis_citation criterion
- **THEN** the system SHALL apply layered judgment:
  - PASS if core laws and judicial interpretations are cited with exact document numbers (e.g., 法释〔2020〕17 号)
  - HALF_PASS if core laws are cited with general references (e.g., "Civil Code + relevant judicial interpretations")
  - FAIL if core laws are not cited or cited laws are repealed
- **AND** accept generalized citations as partial compliance

### Requirement: Differentiated Criteria by Contract Classification
The system SHALL apply different evaluation criteria based on contract type classification (named_contract vs unnamed_contract). Named contracts SHALL be evaluated against Civil Code mandatory clauses, while unnamed contracts SHALL be evaluated against industry standards and governing statutes.

#### Scenario: Evaluate a named contract with Civil Code criteria
- **WHEN** evaluating a named contract (e.g., sale, lease, loan)
- **THEN** the system SHALL apply Civil Code-based criteria specific to that contract type
- **AND** check for mandatory clauses defined in the corresponding Civil Code chapter

#### Scenario: Evaluate an unnamed contract with industry standard criteria
- **WHEN** evaluating an unnamed contract (e.g., company_formation, employment, insurance)
- **THEN** the system SHALL apply industry standard criteria based on governing statutes
- **AND** check for core mandatory clauses defined in the industry standard reference table

### Requirement: Flexible Governing Law Citation
The system SHALL accept flexible governing law citations, including references in "Recitals", "Dispute Resolution", or other sections, not just dedicated "Applicable Law" clauses.

#### Scenario: Accept governing law citation in Recitals
- **WHEN** a contract references applicable law in the "Recitals" section
- **THEN** the system SHALL recognize this as a valid governing law citation
- **AND** apply HALF_PASS judgment to the governing_law_present criterion

#### Scenario: Accept governing law citation in Dispute Resolution
- **WHEN** a contract references applicable law in the "Dispute Resolution" section
- **THEN** the system SHALL recognize this as a valid governing law citation
- **AND** apply HALF_PASS judgment to the governing_law_present criterion

#### Scenario: Require dedicated clause for full compliance
- **WHEN** a contract has a dedicated "Applicable Law" clause
- **THEN** the system SHALL apply PASS judgment to the governing_law_present criterion
- **AND** recognize this as the preferred format

### Requirement: Simplified Legal Citation Requirements
The system SHALL simplify legal citation requirements, accepting generalized citations (e.g., "Civil Code + relevant judicial interpretations") as partial compliance, while still requiring exact document numbers for full compliance.

#### Scenario: Accept generalized legal citation
- **WHEN** a contract cites "Civil Code + relevant judicial interpretations" without exact document numbers
- **THEN** the system SHALL apply HALF_PASS judgment to the legal_basis_citation criterion
- **AND** provide feedback suggesting the addition of exact document numbers

#### Scenario: Require exact document numbers for full compliance
- **WHEN** a contract cites laws with exact document numbers (e.g., 法释〔2020〕17 号)
- **THEN** the system SHALL apply PASS judgment to the legal_basis_citation criterion
- **AND** recognize this as the preferred format

#### Scenario: Reject fabricated or repealed laws
- **WHEN** a contract cites fabricated or repealed laws
- **THEN** the system SHALL apply FAIL judgment to the legal_citation_accuracy criterion
- **AND** provide specific feedback on which citations are invalid

### Requirement: Evaluation Criteria Versioning
The system SHALL support multiple versions of evaluation criteria (v1, v2, v3), allowing gradual migration and backward compatibility. New criteria versions SHALL be created through a controlled process with expert review and testing.

#### Scenario: Create a new criteria version
- **WHEN** evaluation criteria are updated
- **THEN** the system SHALL create a new version (e.g., v3) with the updated criteria
- **AND** preserve previous versions (v1, v2) for backward compatibility

#### Scenario: Migrate to a new criteria version
- **WHEN** a new criteria version is approved
- **THEN** the system SHALL allow gradual migration from the old version to the new version
- **AND** support running both versions in parallel during the migration period

#### Scenario: Rollback to a previous criteria version
- **WHEN** issues are discovered with a new criteria version
- **THEN** the system SHALL allow rollback to a previous version
- **AND** preserve all evaluation results from the new version for analysis

### Requirement: Evaluation Criteria Testing Framework
The system SHALL provide a testing framework for validating new evaluation criteria versions before deployment. The framework SHALL support A/B testing, regression testing, and performance benchmarking.

#### Scenario: Run A/B test on new criteria
- **WHEN** a new criteria version is created
- **THEN** the system SHALL run A/B tests comparing the new version against the old version
- **AND** measure pass rates, false positives, and false negatives

#### Scenario: Run regression test on existing contracts
- **WHEN** a new criteria version is created
- **THEN** the system SHALL run regression tests on a set of existing contracts
- **AND** verify that the new criteria do not introduce unexpected failures

#### Scenario: Benchmark evaluation performance
- **WHEN** a new criteria version is created
- **THEN** the system SHALL benchmark the evaluation performance (time, cost, accuracy)
- **AND** compare against the old version

### Requirement: Evaluation Criteria Feedback Loop
The system SHALL provide a feedback loop for continuously improving evaluation criteria based on test results, user feedback, and legal expert review.

#### Scenario: Collect feedback from test results
- **WHEN** evaluation criteria are tested
- **THEN** the system SHALL collect feedback on false positives, false negatives, and edge cases
- **AND** use the feedback to improve the criteria

#### Scenario: Collect feedback from users
- **WHEN** users provide feedback on evaluation results
- **THEN** the system SHALL record the feedback
- **AND** use it to improve the criteria in the next version

#### Scenario: Incorporate legal expert review
- **WHEN** legal experts review evaluation criteria
- **THEN** the system SHALL incorporate their feedback
- **AND** update the criteria accordingly

### Requirement: Rubric 与域的解析一致性

评测执行 SHALL 按「域的有效 rubric 集合」解析：该域自有 rubric 优先，其次沿父域链继承；同名 rubric 在子域存在时 SHALL 以子域为准。评测运行记录 SHALL 保存实际使用的 rubric 与其所属域，使「某域最近一次评测」可被确定地回答。

#### Scenario: 同名以子域为准
- **WHEN** 子域存在与父域同名的 rubric 且发起评测
- **THEN** 采用子域那条，运行记录标明的 rubric 所属域为子域

#### Scenario: 按域统计运行结果
- **WHEN** 查询某域的评测历史
- **THEN** 只返回该域（含从其父域继承的 rubric）产生的运行，不混入兄弟域的结果
