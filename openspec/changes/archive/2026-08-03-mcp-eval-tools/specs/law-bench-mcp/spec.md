## MODIFIED Requirements

### Requirement: MCP Server Process
The system SHALL provide a FastMCP server project at `fd-coding-law-bench-mcp/` (importable as `fd_coding_law_bench_mcp`) that exposes law-bench's contract generation, contract evaluation (including rubric/criterion/prompt management, compare orchestration, run inspection, and law-info/legal-refs reads), and clause RAG search as MCP tools. The server SHALL be runnable via `python -m fd_coding_law_bench_mcp` and via `fastmcp run`, SHALL communicate over stdio by default, and SHALL import the existing `src.*` modules in place without relocating or copying them.

#### Scenario: Server starts and registers its tools
- **WHEN** the server is launched with `python -m fd_coding_law_bench_mcp`
- **THEN** a FastMCP stdio server starts and advertises the tools `generate_contract_from_tags`, `evaluate_contract`, `list_rubrics`, `list_runs`, `rag_search`, `get_rubric`, `create_rubric`, `update_rubric`, `delete_rubric`, `add_criterion`, `update_criterion`, `delete_criterion`, `reorder_criteria`, `list_prompts`, `get_prompt`, `create_prompt`, `update_prompt`, `delete_prompt`, `run_compare`, `list_compares`, `get_compare`, `get_compare_matrix`, `get_run_draft`, `get_run_detail`, `list_law_info_types`, `get_law_info`, and `extract_legal_references`

#### Scenario: Server is wired into a client config
- **WHEN** an `.mcp.json` entry points a client at `python -m fd_coding_law_bench_mcp`
- **THEN** the client can invoke each advertised tool and receive a structured response

### Requirement: Evaluate Contract Tool
The `evaluate_contract` tool SHALL evaluate a contract - supplied as either a file path or inline text - against a named rubric by delegating to `src.eval.scoring.evaluate_contract`. It SHALL return `{rubric, judge_model, score, max_score, all_pass, n_passed, n_criteria, criteria_results}`. It SHALL persist the run to the eval database unless `no_store=True`. A missing rubric or unreadable contract SHALL surface to the client as a tool error. The `list_rubrics` tool SHALL wrap `src.eval.rubric.list_rubrics` and the `list_runs` tool SHALL wrap `src.eval.store.list_runs`. The `list_rubrics` tool SHALL accept an optional `include_counts: bool` (default `False`): when `True` it SHALL delegate to `src.eval.rubric_crud.list_rubrics_with_counts` and each row SHALL carry `id`, `criterion_count`, and `is_harbor` in addition to `name`/`context`/`source`; when `False` (or unset) it SHALL return `{name, context, source}` rows unchanged. The `get_run_detail(run_id)` tool SHALL delegate to `src.eval.store.get_run` and SHALL return a single run's run-level fields plus its ordered `criteria_results`; an unknown `run_id` SHALL surface to the client as a tool error.

#### Scenario: Evaluate inline contract text without persisting
- **WHEN** `evaluate_contract` is called with `contract="# 服务协议\n..."` (inline text), `rubric="contract_drafting_v1"`, `no_store=True`
- **THEN** the result contains `score`, `max_score`, `all_pass`, and `criteria_results`, and no row is written to the eval database

#### Scenario: Missing rubric surfaces as an error
- **WHEN** `evaluate_contract` is called with a rubric name that does not exist
- **THEN** the tool returns an error to the client and no run is persisted

#### Scenario: list_rubrics returns available rubrics
- **WHEN** `list_rubrics` is called with no arguments (or `include_counts=False`)
- **THEN** it returns the rubric rows with `name`, `context`, and `source`

#### Scenario: list_rubrics with include_counts enriches each row
- **WHEN** `list_rubrics` is called with `include_counts=True`
- **THEN** each row carries `id`, `name`, `context`, `source`, `criterion_count`, and `is_harbor`

#### Scenario: get_run_detail returns a run and its verdicts
- **WHEN** `get_run_detail` is called with a `run_id` that exists
- **THEN** the result contains the run-level fields (`id`, `rubric_name`, `score`, `all_pass`, `n_passed`, `n_criteria`, `scored_at`) and an ordered `criteria_results` list

#### Scenario: get_run_detail on an unknown run surfaces an error
- **WHEN** `get_run_detail` is called with a `run_id` that does not exist
- **THEN** the tool returns an error to the client

## ADDED Requirements

### Requirement: Rubric and Criterion Management Tools
The MCP server SHALL expose the rubric and criterion management surface by wrapping `src.eval.rubric_crud`: `get_rubric(name)` (delegates to `get_rubric_detail`), `create_rubric(name, context, description?, criteria?)`, `update_rubric(rubric_id, name, context, description?)`, `delete_rubric(rubric_id)`, `add_criterion(rubric_id, name, description, guidance)`, `update_criterion(criterion_id, name, description, guidance)`, `delete_criterion(criterion_id)`, and `reorder_criteria(rubric_id, ordered_criterion_ids)`. Each tool SHALL import its `src.eval.rubric_crud` dependency at call time. `ManageError` (`NotFoundError`, `ConflictError`, `ValidationError`, `HarborReadOnlyError`) raised by the wrapped module SHALL propagate to the MCP client as a tool error rather than being swallowed. Harbor rubrics (`source LIKE 'harbor:%'`) SHALL remain read-only: every write tool SHALL surface a tool error when invoked on a harbor rubric, delegating that guard to `src.eval.rubric_crud` unchanged (no second guard in the MCP).

#### Scenario: get_rubric returns a rubric and its ordered criteria
- **WHEN** `get_rubric` is called with a known rubric `name`
- **THEN** the result contains the rubric's `id`, `name`, `context`, `source`, `is_harbor`, `criterion_count`, and an ordered `criteria` list

#### Scenario: create_rubric with criteria returns the new rubric
- **WHEN** `create_rubric` is called with `name`, `context`, and a `criteria` list of `{name, description, guidance}` dicts
- **THEN** a local rubric is created and the result is the new rubric detail with its criteria

#### Scenario: Writing to a harbor rubric surfaces an error
- **WHEN** `update_rubric` (or any write tool) is called with the id of a harbor rubric
- **THEN** the tool returns an error to the client and no write occurs

#### Scenario: reorder_criteria with a mismatched id set surfaces an error
- **WHEN** `reorder_criteria` is called with an id list that is not exactly the rubric's current criterion ids
- **THEN** the tool returns a validation error to the client

### Requirement: Prompt Management Tools
The MCP server SHALL expose the generation-prompt management surface by wrapping `src.eval.prompt_crud`: `list_prompts()`, `get_prompt(name)`, `create_prompt(name, contract_type, purpose, content, description?, prompt_type?)`, `update_prompt(prompt_id, name, contract_type, purpose, content, description?, prompt_type?)`, and `delete_prompt(prompt_id)`. Each tool SHALL import its `src.eval.prompt_crud` dependency at call time. `NotFoundError`, `ConflictError`, and `ValidationError` raised by the wrapped module SHALL propagate to the MCP client as a tool error. Prompts are always locally authored and always editable (no harbor analog, no read-only guard).

#### Scenario: list_prompts returns prompts without the content body
- **WHEN** `list_prompts` is called
- **THEN** it returns rows with `id`, `name`, `contract_type`, `purpose`, `source`, `prompt_type`, `description`, and `created_at` (no `content`)

#### Scenario: get_prompt returns the full record including content
- **WHEN** `get_prompt` is called with a known prompt `name`
- **THEN** the result includes the prompt `content`

#### Scenario: create_prompt then get_prompt round-trips
- **WHEN** `create_prompt` is called with `name`, `contract_type`, `purpose`, and `content`, then `get_prompt` is called with that `name`
- **THEN** the returned record matches the created fields

#### Scenario: delete_prompt on an unknown id surfaces an error
- **WHEN** `delete_prompt` is called with a `prompt_id` that does not exist
- **THEN** the tool returns an error to the client

### Requirement: Compare Tools
The MCP server SHALL expose compare orchestration and reads by wrapping `src.eval.compare` and `src.eval.store`: `run_compare(contract_type, rubric_name, task_desc, prompt_names, n_drafts=1, label?)`, `list_compares(limit=20)`, `get_compare(compare_id)`, `get_compare_matrix(compare_id)`, and `get_run_draft(compare_id, run_id)`. `run_compare` SHALL resolve `prompt_names` to prompt records via `src.eval.compare.load_prompts`, then call `src.eval.compare.run_compare` unchanged (drafter-only generation via the DRAFTER model plus the existing `evaluate_contract` judge) and SHALL persist the grouped compare. `get_compare_matrix` SHALL return `src.eval.compare.build_matrix(src.eval.store.get_compare(compare_id))`. `NotFoundError`, `ValidationError`, and `KeyError` SHALL propagate to the MCP client as a tool error.

#### Scenario: run_compare with fewer than two prompt names surfaces an error
- **WHEN** `run_compare` is called with a single prompt name
- **THEN** the tool returns a validation error to the client and no compare is persisted

#### Scenario: list_compares returns recent compares
- **WHEN** `list_compares` is called
- **THEN** it returns the most recent compares with `id`, `label`, `contract_type`, `rubric_name`, `n_drafts`, and `created_at`

#### Scenario: get_compare on an unknown id surfaces an error
- **WHEN** `get_compare` is called with a `compare_id` that does not exist
- **THEN** the tool returns an error to the client

#### Scenario: get_compare_matrix returns the criteria × prompts matrix
- **WHEN** `get_compare_matrix` is called with a known `compare_id`
- **THEN** the result contains `criteria`, `columns` (one per prompt), `cells` keyed by prompt name, and `n_drafts`

### Requirement: Law-Info and Legal-References Tools
The MCP server SHALL expose read-only law-info and legal-references helpers by wrapping `src.eval.law_info` and `src.eval.legal_refs`: `list_law_info_types()`, `get_law_info(contract_type)`, and `extract_legal_references()`. `get_law_info` SHALL delegate to `src.eval.law_info.get_law_info` and SHALL surface `NotFoundError` as a tool error when no row exists for the type. `extract_legal_references` SHALL aggregate `src.eval.law_info.all_law_info` through `src.eval.legal_refs.extract_references` and return the categorized, deduplicated law-reference index. These tools SHALL be read-only.

#### Scenario: list_law_info_types returns types with their sources
- **WHEN** `list_law_info_types` is called
- **THEN** it returns rows with `key`, `zh_name`, and a `sources` list

#### Scenario: get_law_info on an unknown type surfaces an error
- **WHEN** `get_law_info` is called with a `contract_type` that has no law_info row
- **THEN** the tool returns an error to the client

#### Scenario: extract_legal_references returns categorized laws
- **WHEN** `extract_legal_references` is called and law_info rows exist
- **THEN** it returns laws each with `name`, `category`, `category_zh`, `contract_types`, `sources`, and `occurrences`, sorted by category then name

### Requirement: Tool Registration and Test Coverage
The MCP server SHALL register, on startup, the full expected tool set: `generate_contract_from_tags`, `evaluate_contract`, `list_rubrics`, `list_runs`, `rag_search`, `get_rubric`, `create_rubric`, `update_rubric`, `delete_rubric`, `add_criterion`, `update_criterion`, `delete_criterion`, `reorder_criteria`, `list_prompts`, `get_prompt`, `create_prompt`, `update_prompt`, `delete_prompt`, `run_compare`, `list_compares`, `get_compare`, `get_compare_matrix`, `get_run_draft`, `get_run_detail`, `list_law_info_types`, `get_law_info`, and `extract_legal_references`. Every advertised tool SHALL be covered by at least one hermetic test that monkeypatches its `src.*` dependency so that no DB, LLM, judge endpoint, or network is required. The test suite SHALL include a registration assertion that introspects the server's registered tool names and fails if the set differs from the expected set above.

#### Scenario: Server advertises the full expected tool set
- **WHEN** the server's registered tool names are introspected
- **THEN** they match the expected set exactly (no missing, no extra, no mis-named tool)

#### Scenario: Every tool has a passing hermetic test
- **WHEN** the MCP test suite runs
- **THEN** every advertised tool is exercised by at least one hermetic test with its `src.*` dependency monkeypatched, and the suite passes without a DB, LLM, or network
