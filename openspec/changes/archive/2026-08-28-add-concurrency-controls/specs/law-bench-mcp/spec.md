## MODIFIED Requirements

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
