# law-bench-mcp Specification

## Purpose
A FastMCP server exposing law-bench's tag/stance-filtered contract generation, contract rubric evaluation, and clause RAG search as MCP tools, wrapping existing `src` modules in place.
## Requirements
### Requirement: MCP Server Process
The system SHALL provide a FastMCP server project at `fd-coding-law-bench-mcp/` (importable as `fd_coding_law_bench_mcp`) that exposes law-bench's contract generation, contract evaluation (including rubric/criterion/prompt management, compare orchestration, run inspection, and law-info/legal-refs reads), and clause RAG search as MCP tools. The server SHALL be runnable via `python -m fd_coding_law_bench_mcp` and via `fastmcp run`, SHALL communicate over stdio by default, and SHALL import the existing `src.*` modules in place without relocating or copying them. Each advertised tool SHALL be registered with a FastMCP `tags={"<concept>"}` kwarg assigning it to exactly one concept group (see the Concept Grouping requirement).

#### Scenario: Server starts and registers its tools
- **WHEN** the server is launched with `python -m fd_coding_law_bench_mcp`
- **THEN** a FastMCP stdio server starts and advertises the tools `contract_generate`, `contract_evaluate`, `rubric_list`, `run_list`, `search_clauses`, `rubric_get`, `rubric_create`, `rubric_update`, `rubric_delete`, `criterion_add`, `criterion_update`, `criterion_delete`, `criterion_reorder`, `prompt_list`, `prompt_get`, `prompt_create`, `prompt_update`, `prompt_delete`, `compare_run`, `compare_list`, `compare_get`, `compare_matrix`, `run_draft`, `run_get`, `law_types`, `law_info`, and `law_references`

#### Scenario: Server is wired into a client config
- **WHEN** an `.mcp.json` entry points a client at `python -m fd_coding_law_bench_mcp`
- **THEN** the client can invoke each advertised tool and receive a structured response

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

### Requirement: Current Custom Tag Discovery
The `contract_generate` tool SHALL accept an `include_current_tags: bool` parameter. When `True`, the result SHALL include a `current_tags` field holding the live in-memory `TAG_VOCAB` after `load_vocab_from_db` - i.e. the universal starter set (`stance`/`strength`/`risk`/`mandatory`) merged with every row in the `tag_dims` table AND any dimension registered at runtime via `register_tag_dim` (the temporary custom tags). When `False`, the `current_tags` field SHALL be omitted. The returned vocabulary SHALL reflect the state at call time, so a dimension registered in-process but not persisted to `tag_dims` still appears.

#### Scenario: include_current_tags returns the live vocabulary
- **WHEN** `contract_generate` is called with a known `contract_type` and `include_current_tags=True`
- **THEN** the result contains `current_tags` mapping each known dimension to its allowed values, including at least `stance`, `strength`, `risk`, and `mandatory`

#### Scenario: A runtime-registered temporary dim appears in current_tags
- **WHEN** a caller registers a temporary dimension via `register_tag_dim("vam_mechanism", ["equity_adjust", "cash_compensation"])` in the same process and then calls `contract_generate(..., include_current_tags=True)`
- **THEN** `current_tags["vam_mechanism"]` contains `["equity_adjust", "cash_compensation"]` even though no such row exists in `tag_dims`

#### Scenario: include_current_tags=False omits the field
- **WHEN** `contract_generate` is called with `include_current_tags=False` (or unset)
- **THEN** the result has no `current_tags` field

### Requirement: Evaluate Contract Tool
The `contract_evaluate` tool SHALL evaluate a contract - supplied as either a file path or inline text - against a named rubric by delegating to `src.eval.scoring.evaluate_contract`. It SHALL return `{rubric, judge_model, score, max_score, all_pass, n_passed, n_criteria, criteria_results}`. It SHALL persist the run to the eval database unless `no_store=True`. A missing rubric or unreadable contract SHALL surface to the client as a tool error. The `rubric_list` tool SHALL wrap `src.eval.rubric.list_rubrics` and the `run_list` tool SHALL wrap `src.eval.store.list_runs`. The `rubric_list` tool SHALL accept an optional `include_counts: bool` (default `False`): when `True` it SHALL delegate to `src.eval.rubric_crud.list_rubrics_with_counts` and each row SHALL carry `id`, `criterion_count`, and `is_harbor` in addition to `name`/`context`/`source`; when `False` (or unset) it SHALL return `{name, context, source}` rows unchanged. The `run_get(run_id)` tool SHALL delegate to `src.eval.store.get_run` and SHALL return a single run's run-level fields plus its ordered `criteria_results`; an unknown `run_id` SHALL surface to the client as a tool error. `contract_evaluate` SHALL be tagged `contracts`; `rubric_list` SHALL be tagged `rubrics`; `run_list` SHALL be tagged `eval`; `run_get` SHALL be tagged `eval`.

#### Scenario: Evaluate inline contract text without persisting
- **WHEN** `contract_evaluate` is called with `contract="# 服务协议\n..."` (inline text), `rubric="contract_drafting_v1"`, `no_store=True`
- **THEN** the result contains `score`, `max_score`, `all_pass`, and `criteria_results`, and no row is written to the eval database

#### Scenario: Missing rubric surfaces as an error
- **WHEN** `contract_evaluate` is called with a rubric name that does not exist
- **THEN** the tool returns an error to the client and no run is persisted

#### Scenario: rubric_list returns available rubrics
- **WHEN** `rubric_list` is called with no arguments (or `include_counts=False`)
- **THEN** it returns the rubric rows with `name`, `context`, and `source`

#### Scenario: rubric_list with include_counts enriches each row
- **WHEN** `rubric_list` is called with `include_counts=True`
- **THEN** each row carries `id`, `name`, `context`, `source`, `criterion_count`, and `is_harbor`

#### Scenario: run_get returns a run and its verdicts
- **WHEN** `run_get` is called with a `run_id` that exists
- **THEN** the result contains the run-level fields (`id`, `rubric_name`, `score`, `all_pass`, `n_passed`, `n_criteria`, `scored_at`) and an ordered `criteria_results` list

#### Scenario: run_get on an unknown run surfaces an error
- **WHEN** `run_get` is called with a `run_id` that does not exist
- **THEN** the tool returns an error to the client

### Requirement: RAG Search Tool
The `search_clauses` tool SHALL return ranked chunks for a natural-language query by delegating to `src.search.query.search(query, top_k)` (default `top_k=5`), returning a list of `{text, source_path, score}`. On any backend failure (Elasticsearch / embedding endpoint / MinIO unreachable), it SHALL return an empty list and SHALL NOT raise to the client. It SHALL be tagged `search`.

#### Scenario: Query returns ranked chunks
- **WHEN** `search_clauses` is called with `query="试用期期限"`, `top_k=3`, and the retrieval backend is reachable
- **THEN** it returns up to 3 chunks each with `text`, `source_path`, and numeric `score`

#### Scenario: Backend failure degrades to empty
- **WHEN** `search_clauses` is called and the retrieval backend raises an exception
- **THEN** the tool returns `[]` and does not raise

### Requirement: Wrap-in-Place Without Relocation or Mutation
The MCP server SHALL import `src.eval`, `src.search`, `src.contracts`, and `src.clauses` from their existing on-disk locations and SHALL NOT relocate, copy, or mutate those modules. Errors raised by wrapped `src` modules (other than `search_clauses`'s graceful-degradation path, which returns `[]`) SHALL propagate to the MCP client as tool errors rather than being silently swallowed.

#### Scenario: Existing module paths are unchanged
- **WHEN** the MCP server is installed and run
- **THEN** `src/eval/`, `src/search/`, `src/contracts/`, and `src/clauses/` remain at their original repo paths and are imported, not copied into the MCP package

#### Scenario: A wrapped-module error reaches the client
- **WHEN** a wrapped `src` call (other than `search_clauses`) raises a `ValueError`
- **THEN** the MCP client receives a tool error containing the message, rather than a silent empty result

### Requirement: Concept Grouping via FastMCP Tags
Every tool the server advertises SHALL be registered with a FastMCP `tags={"<concept>"}` kwarg that assigns it to exactly one concept group. The concept groups SHALL be `contracts`, `rubrics`, `prompts`, `eval`, `search`, `law`, and `tags`. The `contracts` group SHALL contain `contract_generate` and `contract_evaluate`; `rubrics` SHALL contain the `rubric_*` and `criterion_*` tools; `prompts` SHALL contain the `prompt_*` tools; `eval` SHALL contain the `compare_*` and `run_*` tools; `search` SHALL contain `search_clauses`; `law` SHALL contain the `law_*` tools; `tags` SHALL contain the `tag_*` tools.

#### Scenario: Every advertised tool carries a concept tag
- **WHEN** the server is launched and its tools are enumerated
- **THEN** each tool belongs to exactly one of the seven concept groups via its FastMCP `tags` value

#### Scenario: Related entities share a concept group
- **WHEN** the `rubric_*` and `criterion_*` tools are enumerated
- **THEN** both sets are tagged `rubrics`, so criterion management groups with rubric management

### Requirement: Tag Vocabulary Listing Tool
The `tag_vocab_list` tool SHALL return the merged flat tag vocabulary for a contract type by delegating to `src.clauses.tags.tag_vocab_for_type(contract_type)`, returning `{dim: [allowed values]}` for every dimension valid for that type (universal starter dims merged with type-specific dims). It SHALL be read-only: it SHALL NOT write to the `tag_dims` table or register new dimensions. It MAY refresh the in-memory `TAG_VOCAB` from `tag_dims` via `load_vocab_from_db` (mirroring `contract_generate`'s `include_current_tags` path) so type-specific dims are reflected. It SHALL be tagged `tags`.

#### Scenario: List merged vocabulary for a contract type
- **WHEN** `tag_vocab_list` is called with `contract_type="sale"`
- **THEN** it returns a dict mapping each valid dimension (including universal `stance` / `strength` / `risk` / `mandatory` and any sale-specific dims) to its allowed values

#### Scenario: Universal-only vocabulary when no type given
- **WHEN** `tag_vocab_list` is called with `contract_type=None` (or unset)
- **THEN** it returns only the universal starter dimensions

### Requirement: Tag Validation Tool
The `tag_validate` tool SHALL validate a tag dict against the controlled vocabulary by delegating to `src.clauses.tags.validate_tags(tags, contract_type)`. It SHALL return the cleaned dict (unknown keys dropped). For a controlled dim with an invalid value, it SHALL surface the `ValueError` raised by `validate_tags` to the client as a tool error. It SHALL be read-only and tagged `tags`.

#### Scenario: Valid tags are returned cleaned
- **WHEN** `tag_validate` is called with `tags={"stance": "pro_a", "mood": "happy"}`, `contract_type="sale"`
- **THEN** it returns `{"stance": "pro_a"}` (the unknown `mood` key is dropped)

#### Scenario: Invalid controlled value surfaces as an error
- **WHEN** `tag_validate` is called with `tags={"stance": "pro_A"}`
- **THEN** the tool returns an error to the client indicating the invalid value and the allowed set


### Requirement: Contract Pipeline Tools
The MCP server SHALL expose a contract-pipeline surface in `tools/pipeline.py` (concept tag `pipeline`): `pipeline_run`, `pipeline_list`, and `pipeline_get`. `pipeline_run(contract_type, tags=None, stance=None, rubric=None, task_desc=None, fill_mode="llm", temperature=0.0, max_iterations=3, custom_clause_ids=None)` SHALL delegate to a LangGraph `StateGraph` (see the `contract-pipeline` capability) that generates, fills, evaluates, and self-heals, then persists one `pipeline_runs` row; it SHALL return `{pipeline_run_id, eval_run_id, score, max_score, all_pass, n_passed, n_criteria, summary, iteration, actions_taken, recommendations}`. `pipeline_list(limit=20)` SHALL return recent `pipeline_runs` rows newest-first. `pipeline_get(pipeline_id)` SHALL return the `pipeline_runs` row joined to its `eval_runs` per-criterion verdicts (via `run_get(eval_run_id)`); an unknown `pipeline_id` SHALL surface as a tool error. Each tool SHALL import its `src` / pipeline dependencies at call time, and `NotFoundError` / `ValidationError` / `CoherenceError` SHALL propagate as tool errors.

#### Scenario: pipeline_run produces an evaluated, persisted contract
- **WHEN** `pipeline_run` is called with `contract_type="sale"`, `tags={"scenario":"农产品买卖","stance":"balanced"}`
- **THEN** a `pipeline_runs` row is created with `contract_type`, `tags`, `filled_text`, `fill_values`, `fill_temperature`, `eval_run_id` (pointing at the stored `eval_runs` row), `score`, and `iteration`, and the returned dict carries `pipeline_run_id` and `eval_run_id`

#### Scenario: pipeline_run defaults rubric to the latest version
- **WHEN** `pipeline_run` is called with `contract_type="sale"` and no `rubric`
- **THEN** the rubric resolves to `contract_sale_v2` (highest `vN`), and the run is judged against it

#### Scenario: pipeline_run with an unknown contract type surfaces an error
- **WHEN** `pipeline_run` is called with `contract_type="nope"`
- **THEN** the tool returns an error and no `pipeline_runs` row is written

#### Scenario: pipeline_list returns recent runs
- **WHEN** `pipeline_list` is called with `limit=5`
- **THEN** it returns up to 5 `pipeline_runs` rows ordered newest-first

#### Scenario: pipeline_get returns a run and its verdicts
- **WHEN** `pipeline_get` is called with an existing `pipeline_id`
- **THEN** the result contains the pipeline fields (`contract_type`, `tags`, `filled_text`, `fill_values`, `score`, `actions_taken`, `recommendations`) plus the ordered `criteria_results` from the linked eval run

#### Scenario: pipeline_get on an unknown id surfaces an error
- **WHEN** `pipeline_get` is called with a `pipeline_id` that does not exist
- **THEN** the tool returns an error to the client

### Requirement: Generate Contract Tool Extensions
The `contract_generate` tool SHALL additionally accept an optional `custom_clause_ids: list[int] | None = None`, forwarded to `src.clauses.assemble.generate_contract_assembled(custom_clause_ids=...)` so a caller can select a specific custom-clause set (e.g. exclude a thin override). When `custom_clause_ids` is `None` the behavior SHALL be unchanged (backward-compatible). The tool SHALL additionally return `body_text` - the assembled Markdown body with `{{slot}}` placeholders (already materialized internally by `generate_contract_assembled`) - alongside the existing `docx_path` / `pdf_path` / `slots` / `instructions` / `law_refs` / `diagnostics` fields, so a downstream fill step can operate on text without a DOCX round-trip.

#### Scenario: contract_generate forwards custom_clause_ids
- **WHEN** `contract_generate` is called with `contract_type="sale"`, `tags={"stance":"balanced"}`, `custom_clause_ids=[]`
- **THEN** no custom clause is selected (base wins for every section) and the result still carries `docx_path`, `slots`, `instructions`, and `body_text`

#### Scenario: contract_generate returns body_text
- **WHEN** `contract_generate` is called with `contract_type="sale"`
- **THEN** the result includes a non-empty `body_text` containing the `{{slot}}` placeholders, in addition to `docx_path`

#### Scenario: contract_generate without custom_clause_ids is unchanged
- **WHEN** `contract_generate` is called without `custom_clause_ids`
- **THEN** the assembled contract and returned fields match the pre-extension behavior

### Requirement: Evaluate Contract Tool Run Id
The `contract_evaluate` tool SHALL additionally return `run_id` - the id of the stored `eval_runs` row (the value returned by `src.eval.store.store_result`) - when `no_store` is `False`. When `no_store` is `True`, `run_id` SHALL be `null`. All existing fields (`rubric`, `score`, `criteria_results`, ...) SHALL remain unchanged.

#### Scenario: contract_evaluate returns the stored run_id
- **WHEN** `contract_evaluate` is called with a valid contract and `no_store=False`
- **THEN** the result includes a non-null `run_id` identifying the persisted `eval_runs` row

#### Scenario: contract_evaluate with no_store has null run_id
- **WHEN** `contract_evaluate` is called with `no_store=True`
- **THEN** `run_id` is `null` and no `eval_runs` row is written

### Requirement: Rubric and Criterion Management Tools
The MCP server SHALL expose the rubric and criterion management surface by wrapping `src.eval.rubric_crud`: `rubric_get(name)` (delegates to `get_rubric_detail`), `rubric_create(name, context, description?, criteria?)`, `rubric_update(rubric_id, name, context, description?)`, `rubric_delete(rubric_id)`, `criterion_add(rubric_id, name, description, guidance)`, `criterion_update(criterion_id, name, description, guidance)`, `criterion_delete(criterion_id)`, and `criterion_reorder(rubric_id, ordered_criterion_ids)`. Each tool SHALL import its `src.eval.rubric_crud` dependency at call time. `ManageError` (`NotFoundError`, `ConflictError`, `ValidationError`, `HarborReadOnlyError`) raised by the wrapped module SHALL propagate to the MCP client as a tool error rather than being swallowed. Harbor rubrics (`source LIKE 'harbor:%'`) SHALL remain read-only: every write tool SHALL surface a tool error when invoked on a harbor rubric, delegating that guard to `src.eval.rubric_crud` unchanged (no second guard in the MCP). The `rubric_*` and `criterion_*` tools SHALL be tagged `rubrics`.

#### Scenario: rubric_get returns a rubric and its ordered criteria
- **WHEN** `rubric_get` is called with a known rubric `name`
- **THEN** the result contains the rubric's `id`, `name`, `context`, `source`, `is_harbor`, `criterion_count`, and an ordered `criteria` list

#### Scenario: rubric_create with criteria returns the new rubric
- **WHEN** `rubric_create` is called with `name`, `context`, and a `criteria` list of `{name, description, guidance}` dicts
- **THEN** a local rubric is created and the result is the new rubric detail with its criteria

#### Scenario: Writing to a harbor rubric surfaces an error
- **WHEN** `rubric_update` (or any write tool) is called with the id of a harbor rubric
- **THEN** the tool returns an error to the client and no write occurs

#### Scenario: criterion_reorder with a mismatched id set surfaces an error
- **WHEN** `criterion_reorder` is called with an id list that is not exactly the rubric's current criterion ids
- **THEN** the tool returns a validation error to the client

### Requirement: Prompt Management Tools
The MCP server SHALL expose the generation-prompt management surface by wrapping `src.eval.prompt_crud`: `prompt_list()`, `prompt_get(name)`, `prompt_create(name, contract_type, purpose, content, description?, prompt_type?)`, `prompt_update(prompt_id, name, contract_type, purpose, content, description?, prompt_type?)`, and `prompt_delete(prompt_id)`. Each tool SHALL import its `src.eval.prompt_crud` dependency at call time. `NotFoundError`, `ConflictError`, and `ValidationError` raised by the wrapped module SHALL propagate to the MCP client as a tool error. Prompts are always locally authored and always editable (no harbor analog, no read-only guard). The `prompt_*` tools SHALL be tagged `prompts`.

#### Scenario: prompt_list returns prompts without the content body
- **WHEN** `prompt_list` is called
- **THEN** it returns rows with `id`, `name`, `contract_type`, `purpose`, `source`, `prompt_type`, `description`, and `created_at` (no `content`)

#### Scenario: prompt_get returns the full record including content
- **WHEN** `prompt_get` is called with a known prompt `name`
- **THEN** the result includes the prompt `content`

#### Scenario: prompt_create then prompt_get round-trips
- **WHEN** `prompt_create` is called with `name`, `contract_type`, `purpose`, and `content`, then `prompt_get` is called with that `name`
- **THEN** the returned record matches the created fields

#### Scenario: prompt_delete on an unknown id surfaces an error
- **WHEN** `prompt_delete` is called with a `prompt_id` that does not exist
- **THEN** the tool returns an error to the client

### Requirement: Compare Tools
The MCP server SHALL expose compare orchestration and reads by wrapping `src.eval.compare` and `src.eval.store`: `compare_run(contract_type, rubric_name, task_desc, prompt_names, n_drafts=1, label?, concurrency=1)`, `compare_list(limit=20)`, `compare_get(compare_id)`, `compare_matrix(compare_id)`, and `run_draft(compare_id, run_id)`. `compare_run` SHALL resolve `prompt_names` to prompt records via `src.eval.compare.load_prompts`, then call `src.eval.compare.run_compare` unchanged (drafter-only generation via the DRAFTER model plus the existing `src.eval.scoring.evaluate_contract` judge) and SHALL persist the grouped compare; its `concurrency` parameter SHALL bound parallel draft generation, SHALL be clamped to [1, 8], and the effective value SHALL be included in the tool result. `compare_matrix` SHALL return `src.eval.compare.build_matrix(src.eval.store.get_compare(compare_id))`. `NotFoundError`, `ValidationError`, and `KeyError` SHALL propagate to the MCP client as a tool error. The `compare_*` tools SHALL be tagged `eval`; `run_draft` SHALL be tagged `eval`.

#### Scenario: compare_run with fewer than two prompt names surfaces an error
- **WHEN** `compare_run` is called with a single prompt name
- **THEN** the tool returns a validation error to the client and no compare is persisted

#### Scenario: compare_run with a concurrency override
- **WHEN** `compare_run` is called with three prompt names, n_drafts 2, and concurrency 4
- **THEN** the compare runs with at most 4 drafts generated simultaneously
- **AND** the tool result reports the effective concurrency and the persisted compare matches a concurrency-1 run of the same inputs in content and row order

#### Scenario: compare_run clamps oversized concurrency
- **WHEN** `compare_run` is called with concurrency 50
- **THEN** the compare runs with effective concurrency 8 and the result reports 8

#### Scenario: compare_list returns recent compares
- **WHEN** `compare_list` is called
- **THEN** it returns the most recent compares with `id`, `label`, `contract_type`, `rubric_name`, `n_drafts`, and `created_at`

#### Scenario: compare_get on an unknown id surfaces an error
- **WHEN** `compare_get` is called with a `compare_id` that does not exist
- **THEN** the tool returns an error to the client

#### Scenario: compare_matrix returns the criteria x prompts matrix
- **WHEN** `compare_matrix` is called with a known `compare_id`
- **THEN** the result contains `criteria`, `columns` (one per prompt), `cells` keyed by prompt name, and `n_drafts`
### Requirement: Law-Info and Legal-References Tools
The MCP server SHALL expose read-only law-info and legal-references helpers by wrapping `src.eval.law_info` and `src.eval.legal_refs`: `law_types()`, `law_info(contract_type)`, and `law_references()`. `law_info` SHALL delegate to `src.eval.law_info.get_law_info` and SHALL surface `NotFoundError` as a tool error when no row exists for the type. `law_references` SHALL aggregate `src.eval.law_info.all_law_info` through `src.eval.legal_refs.extract_references` and return the categorized, deduplicated law-reference index. These tools SHALL be read-only and tagged `law`.

#### Scenario: law_types returns types with their sources
- **WHEN** `law_types` is called
- **THEN** it returns rows with `key`, `zh_name`, and a `sources` list

#### Scenario: law_info on an unknown type surfaces an error
- **WHEN** `law_info` is called with a `contract_type` that has no law_info row
- **THEN** the tool returns an error to the client

#### Scenario: law_references returns categorized laws
- **WHEN** `law_references` is called and law_info rows exist
- **THEN** it returns laws each with `name`, `category`, `category_zh`, `contract_types`, `sources`, and `occurrences`, sorted by category then name

### Requirement: Tool Registration and Test Coverage
The MCP server SHALL register, on startup, the eval-lifecycle tool set: `contract_generate`, `contract_evaluate`, `rubric_list`, `run_list`, `search_clauses`, `rubric_get`, `rubric_create`, `rubric_update`, `rubric_delete`, `criterion_add`, `criterion_update`, `criterion_delete`, `criterion_reorder`, `prompt_list`, `prompt_get`, `prompt_create`, `prompt_update`, `prompt_delete`, `compare_run`, `compare_list`, `compare_get`, `compare_matrix`, `run_draft`, `run_get`, `law_types`, `law_info`, and `law_references` (in addition to tools defined by other requirements such as pipeline and tag tools). Every advertised tool SHALL be covered by at least one hermetic test that monkeypatches its `src.*` dependency so that no DB, LLM, judge endpoint, or network is required. The test suite SHALL include a registration assertion that introspects the server's registered tool names and fails if any of the expected tools above is missing or mis-named.

#### Scenario: Server advertises the expected eval-lifecycle tools
- **WHEN** the server's registered tool names are introspected
- **THEN** every tool in the expected eval-lifecycle set is present and correctly named (no missing, no mis-named tool)

#### Scenario: Every tool has a passing hermetic test
- **WHEN** the MCP test suite runs
- **THEN** every advertised tool is exercised by at least one hermetic test with its `src.*` dependency monkeypatched, and the suite passes without a DB, LLM, or network

### Requirement: Streamable HTTP Transport
The MCP server SHALL support a streamable-HTTP transport selected by the
`MCP_HTTP_TRANSPORT` environment variable. When the variable is unset or `stdio`, the
server SHALL behave exactly as specified elsewhere in this capability (stdio, no token
required). When it is `http`, the server SHALL serve the same advertised tool set over
streamable HTTP, bound to `MCP_HTTP_HOST` (default `0.0.0.0`) and `MCP_HTTP_PORT`
(default `8080`). When serving HTTP, the server SHALL require a shared access token via
`MCP_HTTP_TOKEN`: if that variable is unset or empty the server SHALL refuse to start
(fail-closed), and any HTTP request that does not present the configured token SHALL be
rejected before any tool executes. The stdio path SHALL NOT require a token. Adding the
HTTP transport SHALL NOT change any tool's name, signature, or behavior.

#### Scenario: Default invocation is unchanged
- **WHEN** the server is launched with `python -m fd_coding_law_bench_mcp` and no
  `MCP_HTTP_TRANSPORT` variable
- **THEN** it runs over stdio exactly as before this requirement existed, with no token
  requirement

#### Scenario: HTTP transport serves the same tool set
- **WHEN** the server is launched with `MCP_HTTP_TRANSPORT=http` and a configured
  `MCP_HTTP_TOKEN`
- **THEN** the tool set advertised over streamable HTTP equals the stdio tool set, and
  an authenticated client can invoke each tool with the same arguments and results

#### Scenario: HTTP without a configured token refuses to start
- **WHEN** the server is launched with `MCP_HTTP_TRANSPORT=http` and no
  `MCP_HTTP_TOKEN`
- **THEN** the server exits with an error before binding any port

#### Scenario: Unauthenticated HTTP requests are rejected
- **WHEN** an HTTP request arrives without the token (or with a wrong token)
- **THEN** it is rejected before any tool dispatch, and no tool executes
### Requirement: Tool Denylist
The MCP server SHALL support excluding a configured set of tools from advertisement via environment configuration (`MCP_TOOL_DENYLIST`, comma-separated tool names). Excluded tools SHALL NOT appear in tool listings and SHALL NOT be invocable. When the setting is unset or empty, all tools SHALL be advertised (behavior unchanged for existing clients). The setting SHALL apply on both stdio and streamable HTTP transports.

#### Scenario: Denylisted tools are not advertised
- **WHEN** the server starts with `MCP_TOOL_DENYLIST=clause_delete,rubric_delete,criterion_delete,prompt_delete` and a client lists tools
- **THEN** the denylisted tools are absent from the listing and all other tools are present

#### Scenario: Denylisted tool is not invocable
- **WHEN** a client calls a denylisted tool by name
- **THEN** the call fails as an unknown tool and no data is changed

#### Scenario: Default keeps the full toolset
- **WHEN** the server starts without `MCP_TOOL_DENYLIST`
- **THEN** all tools are advertised exactly as before this change
