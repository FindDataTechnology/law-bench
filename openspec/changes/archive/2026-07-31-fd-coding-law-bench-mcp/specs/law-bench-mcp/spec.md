## ADDED Requirements

### Requirement: MCP Server Process
The system SHALL provide a FastMCP server project at `fd-coding-law-bench-mcp/` (importable as `fd_coding_law_bench_mcp`) that exposes law-bench's contract generation, contract evaluation, and clause RAG search as MCP tools. The server SHALL be runnable via `python -m fd_coding_law_bench_mcp` and via `fastmcp run`, SHALL communicate over stdio by default, and SHALL import the existing `src.*` modules in place without relocating or copying them.

#### Scenario: Server starts and registers its tools
- **WHEN** the server is launched with `python -m fd_coding_law_bench_mcp`
- **THEN** a FastMCP stdio server starts and advertises the tools `generate_contract_from_tags`, `evaluate_contract`, `list_rubrics`, `list_runs`, and `rag_search`

#### Scenario: Server is wired into a client config
- **WHEN** an `.mcp.json` entry points a client at `python -m fd_coding_law_bench_mcp`
- **THEN** the client can invoke each advertised tool and receive a structured response

### Requirement: Generate Contract from Tags
The `generate_contract_from_tags` tool SHALL generate a contract deliverable for a given `contract_type` by delegating to `src.contracts.generate_contract`. When `tags` and/or `stance` are supplied, it SHALL delegate to `src.clauses.assemble.generate_contract_assembled` so the custom-clause selection is filtered by the supplied tag/stance dimensions. It SHALL accept `format` (`docx` / `pdf` / `both`, default `pdf`) and `out_dir` (default `output/contracts`), write the deliverable(s) to disk, and return `{docx_path, pdf_path, slots, instructions, laws}` (unset formats map to `None`). An unknown `contract_type` SHALL surface to the client as a tool error.

#### Scenario: Generate a PDF for a known contract type
- **WHEN** `generate_contract_from_tags` is called with `contract_type="sale"`, `format="pdf"`
- **THEN** a `sale.pdf` is written under `output/contracts` and the result `pdf_path` points at it, `docx_path` is `None`, and `slots`/`instructions`/`laws` are populated

#### Scenario: Stance filter is applied to assembled custom clauses
- **WHEN** `generate_contract_from_tags` is called with `contract_type="employment"`, `stance="pro_a"`
- **THEN** the assembled contract body includes only custom clauses whose `tags.stance = "pro_a"` (base and tagged clauses unchanged)

#### Scenario: Unknown contract type surfaces as an error
- **WHEN** `generate_contract_from_tags` is called with `contract_type="not_a_real_type"`
- **THEN** the tool returns an error to the client (no file is written)

### Requirement: Current Custom Tag Discovery
The `generate_contract_from_tags` tool SHALL accept an `include_current_tags: bool` parameter. When `True`, the result SHALL include a `current_tags` field holding the live in-memory `TAG_VOCAB` after `load_vocab_from_db` - i.e. the universal starter set (`stance`/`strength`/`risk`/`mandatory`) merged with every row in the `tag_dims` table AND any dimension registered at runtime via `register_tag_dim` (the temporary custom tags). When `False`, the `current_tags` field SHALL be omitted. The returned vocabulary SHALL reflect the state at call time, so a dimension registered in-process but not persisted to `tag_dims` still appears.

#### Scenario: include_current_tags returns the live vocabulary
- **WHEN** `generate_contract_from_tags` is called with a known `contract_type` and `include_current_tags=True`
- **THEN** the result contains `current_tags` mapping each known dimension to its allowed values, including at least `stance`, `strength`, `risk`, and `mandatory`

#### Scenario: A runtime-registered temporary dim appears in current_tags
- **WHEN** a caller registers a temporary dimension via `register_tag_dim("vam_mechanism", ["equity_adjust", "cash_compensation"])` in the same process and then calls `generate_contract_from_tags(..., include_current_tags=True)`
- **THEN** `current_tags["vam_mechanism"]` contains `["equity_adjust", "cash_compensation"]` even though no such row exists in `tag_dims`

#### Scenario: include_current_tags=False omits the field
- **WHEN** `generate_contract_from_tags` is called with `include_current_tags=False` (or unset)
- **THEN** the result has no `current_tags` field

### Requirement: Evaluate Contract Tool
The `evaluate_contract` tool SHALL evaluate a contract - supplied as either a file path or inline text - against a named rubric by delegating to `src.eval.scoring.evaluate_contract`. It SHALL return `{rubric, judge_model, score, max_score, all_pass, n_passed, n_criteria, criteria_results}`. It SHALL persist the run to the eval database unless `no_store=True`. A missing rubric or unreadable contract SHALL surface to the client as a tool error. The `list_rubrics` tool SHALL wrap `src.eval.rubric.list_rubrics` and the `list_runs` tool SHALL wrap `src.eval.store.list_runs`.

#### Scenario: Evaluate inline contract text without persisting
- **WHEN** `evaluate_contract` is called with `contract="# 服务协议\n..."` (inline text), `rubric="contract_drafting_v1"`, `no_store=True`
- **THEN** the result contains `score`, `max_score`, `all_pass`, and `criteria_results`, and no row is written to the eval database

#### Scenario: Missing rubric surfaces as an error
- **WHEN** `evaluate_contract` is called with a rubric name that does not exist
- **THEN** the tool returns an error to the client and no run is persisted

#### Scenario: list_rubrics returns available rubrics
- **WHEN** `list_rubrics` is called
- **THEN** it returns the rubric rows with `name`, `context`, and `source`

### Requirement: RAG Search Tool
The `rag_search` tool SHALL return ranked chunks for a natural-language query by delegating to `src.search.query.search(query, top_k)` (default `top_k=5`), returning a list of `{text, source_path, score}`. On any backend failure (Elasticsearch / embedding endpoint / MinIO unreachable), it SHALL return an empty list and SHALL NOT raise to the client.

#### Scenario: Query returns ranked chunks
- **WHEN** `rag_search` is called with `query="试用期期限"`, `top_k=3`, and the retrieval backend is reachable
- **THEN** it returns up to 3 chunks each with `text`, `source_path`, and numeric `score`

#### Scenario: Backend failure degrades to empty
- **WHEN** `rag_search` is called and the retrieval backend raises an exception
- **THEN** the tool returns `[]` and does not raise

### Requirement: Wrap-in-Place Without Relocation or Mutation
The MCP server SHALL import `src.eval`, `src.search`, `src.contracts`, and `src.clauses` from their existing on-disk locations and SHALL NOT relocate, copy, or mutate those modules. Errors raised by wrapped `src` modules (other than `rag_search`'s graceful-degradation path, which returns `[]`) SHALL propagate to the MCP client as tool errors rather than being silently swallowed.

#### Scenario: Existing module paths are unchanged
- **WHEN** the MCP server is installed and run
- **THEN** `src/eval/`, `src/search/`, `src/contracts/`, and `src/clauses/` remain at their original repo paths and are imported, not copied into the MCP package

#### Scenario: A wrapped-module error reaches the client
- **WHEN** a wrapped `src` call (other than `rag_search`) raises a `ValueError`
- **THEN** the MCP client receives a tool error containing the message, rather than a silent empty result
