## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: MCP Server Process
The system SHALL provide a FastMCP server project at `fd-coding-law-bench-mcp/` (importable as `fd_coding_law_bench_mcp`) that exposes law-bench's contract generation, contract evaluation, and clause RAG search as MCP tools. The server SHALL be runnable via `python -m fd_coding_law_bench_mcp` and via `fastmcp run`, SHALL communicate over stdio by default, and SHALL import the existing `src.*` modules in place without relocating or copying them. Each advertised tool SHALL be registered with a FastMCP `tags={"<concept>"}` kwarg assigning it to exactly one concept group (see the Concept Grouping requirement).

#### Scenario: Server starts and registers its tools
- **WHEN** the server is launched with `python -m fd_coding_law_bench_mcp`
- **THEN** a FastMCP stdio server starts and advertises the tools `contract_generate`, `contract_evaluate`, `rubric_list`, `run_list`, and `search_clauses`

#### Scenario: Server is wired into a client config
- **WHEN** an `.mcp.json` entry points a client at `python -m fd_coding_law_bench_mcp`
- **THEN** the client can invoke each advertised tool and receive a structured response

### Requirement: Generate Contract from Tags
The `contract_generate` tool SHALL generate a contract deliverable for a given `contract_type` by delegating to `src.contracts.generate_contract`. When `stance` and/or `scenario` are supplied (directly or via `tags["stance"]` / `tags["scenario"]`), it SHALL delegate to `src.clauses.assemble.generate_contract_assembled` so the custom-clause selection is filtered by the supplied `stance` and the tagged-clause selection is filtered by the supplied `scenario` (业务场景). The `tags` dict SHALL NOT recognize `region` or `province` - any such keys SHALL be ignored. It SHALL accept `format` (`docx` / `pdf` / `both`, default `pdf`) and `out_dir` (default `output/contracts`), write the deliverable(s) to disk, and return `{docx_path, pdf_path, slots, instructions, laws}` (unset formats map to `None`). An unknown `contract_type` SHALL surface to the client as a tool error. It SHALL be tagged `contracts`.

#### Scenario: Generate a PDF for a known contract type
- **WHEN** `contract_generate` is called with `contract_type="sale"`, `format="pdf"`
- **THEN** a `sale.pdf` is written under `output/contracts` and the result `pdf_path` points at it, `docx_path` is `None`, and `slots`/`instructions`/`laws` are populated

#### Scenario: Stance filter is applied to assembled custom clauses
- **WHEN** `contract_generate` is called with `contract_type="employment"`, `stance="pro_a"`
- **THEN** the assembled contract body includes only custom clauses whose `tags.stance = "pro_a"` (base and tagged clauses unchanged)

#### Scenario: Scenario filter is applied to assembled tagged clauses
- **WHEN** `contract_generate` is called with `contract_type="sale"`, `tags={"scenario": "建材工业品"}`
- **THEN** the assembled contract body includes `source=tagged` clauses whose `tags.scenario = "建材工业品"` (base and custom clauses follow their respective rules)

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
The `contract_evaluate` tool SHALL evaluate a contract - supplied as either a file path or inline text - against a named rubric by delegating to `src.eval.scoring.evaluate_contract`. It SHALL return `{rubric, judge_model, score, max_score, all_pass, n_passed, n_criteria, criteria_results}`. It SHALL persist the run to the eval database unless `no_store=True`. A missing rubric or unreadable contract SHALL surface to the client as a tool error. The `rubric_list` tool SHALL wrap `src.eval.rubric.list_rubrics` and the `run_list` tool SHALL wrap `src.eval.store.list_runs`. `contract_evaluate` SHALL be tagged `contracts`; `rubric_list` SHALL be tagged `rubrics`; `run_list` SHALL be tagged `eval`.

#### Scenario: Evaluate inline contract text without persisting
- **WHEN** `contract_evaluate` is called with `contract="# 服务协议\n..."` (inline text), `rubric="contract_drafting_v1"`, `no_store=True`
- **THEN** the result contains `score`, `max_score`, `all_pass`, and `criteria_results`, and no row is written to the eval database

#### Scenario: Missing rubric surfaces as an error
- **WHEN** `contract_evaluate` is called with a rubric name that does not exist
- **THEN** the tool returns an error to the client and no run is persisted

#### Scenario: rubric_list returns available rubrics
- **WHEN** `rubric_list` is called
- **THEN** it returns the rubric rows with `name`, `context`, and `source`

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
