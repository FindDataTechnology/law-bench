## ADDED Requirements

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
