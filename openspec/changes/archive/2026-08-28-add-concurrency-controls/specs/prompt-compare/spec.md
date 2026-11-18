## MODIFIED Requirements

### Requirement: Compare Run Orchestration
The system SHALL provide `src/eval/compare.py::run_compare(...)` that, for a fixed area (contract_type, rubric_name, task_desc) and a set of two or more prompts, generates one or more drafts per prompt and evaluates each draft against the named rubric using the existing `evaluate_contract` judge unchanged. Each compare run SHALL be persisted as one `compare_runs` row owning its `eval_runs` rows. Generation SHALL use the drafter-only mode: one direct LLM call per draft via the DRAFTER model, the prompt's `content` as the drafting instruction, the task as input, and the existing templates reference block - `src/crew.py` SHALL NOT be invoked. `run_compare` SHALL accept a `concurrency` parameter (default 1) bounding how many drafts are generated simultaneously across the prompt × draft matrix, clamped to [1, 8]; regardless of the value used, the `eval_runs` rows SHALL be persisted in the same deterministic order as the sequential path (prompt-major, draft-minor), each carrying its own `prompt_name`, `prompt_type`, `variant_label`, and `draft_text`.

#### Scenario: Compare two prompts end-to-end
- **WHEN** `run_compare` is called with contract_type `sale`, rubric `contract_sale_v1`, task `起草一份买卖合同…`, prompts `[draft_sale, draft_sale_v2]`, mode `drafter-only`, n_drafts `1`
- **THEN** one draft is generated per prompt (2 drafts total) using the DRAFTER model
- **AND** each draft is evaluated against `contract_sale_v1` via `evaluate_contract`
- **AND** exactly one `compare_runs` row is created owning two `eval_runs` rows (one per prompt)
- **AND** each `eval_runs` row has `prompt_name`, `prompt_type`, `variant_label`, `draft_text`, and `compare_run_id` populated

#### Scenario: N drafts per prompt aggregate to pass-rates
- **WHEN** `run_compare` is called with n_drafts `3` for two prompts
- **THEN** 6 drafts are generated (3 per prompt) and 6 `eval_runs` rows are created under one `compare_run`
- **AND** the returned grouped result includes, per prompt per criterion, a `k/N` pass-rate across the 3 drafts

#### Scenario: Parallel drafts preserve deterministic persistence
- **WHEN** `run_compare` is called with n_drafts `3` for two prompts and concurrency `4`
- **THEN** at most 4 drafts are generated simultaneously
- **AND** the 6 `eval_runs` rows are persisted in the same order as a concurrency-1 run of the same inputs (prompt-major, draft-minor)
- **AND** each row still carries the `prompt_name` and `draft_text` of its own draft

#### Scenario: Concurrency above the ceiling is clamped
- **WHEN** `run_compare` is called with concurrency `20`
- **THEN** the effective draft concurrency is 8

#### Scenario: Compare does not invoke the crew
- **WHEN** a compare runs
- **THEN** `src/crew.py::ContractDraftingCrew` is never instantiated
- **AND** generation uses `src/llm.py::get_llm("DRAFTER")` directly
