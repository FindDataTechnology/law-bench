## ADDED Requirements

### Requirement: Compare Run Orchestration
The system SHALL provide `src/eval/compare.py::run_compare(...)` that, for a fixed area (contract_type, rubric_name, task_desc) and a set of two or more prompts, generates one or more drafts per prompt and evaluates each draft against the named rubric using the existing `evaluate_contract` judge unchanged. Each compare run SHALL be persisted as one `compare_runs` row owning its `eval_runs` rows. Generation SHALL use the drafter-only mode: one direct LLM call per draft via the DRAFTER model, the prompt's `content` as the drafting instruction, the task as input, and the existing templates reference block - `src/crew.py` SHALL NOT be invoked.

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

#### Scenario: Compare does not invoke the crew
- **WHEN** a compare runs
- **THEN** `src/crew.py::ContractDraftingCrew` is never instantiated
- **AND** generation uses `src/llm.py::get_llm("DRAFTER")` directly

### Requirement: Compare Run Persistence and Query
The system SHALL persist a compare as one `compare_runs` row (label, contract_type, rubric_name, task_desc, gen_mode, n_drafts, created_at) owning its `eval_runs` rows via a snapshotted `compare_run_id`. It SHALL provide `list_compares()` (recent compares, run-level only) and `get_compare(compare_id)` (full grouped result: the `compare_runs` row, its `eval_runs` with `prompt_name`/`prompt_type`/`variant_label`/`draft_text`, and each run's `eval_criteria_results`). All prompt/rubric references SHALL be snapshotted as text so a compare survives later prompt or rubric edits/deletion.

#### Scenario: List recent compares
- **WHEN** a caller lists compares
- **THEN** the most recent compares are returned with id, label, contract_type, rubric_name, n_drafts, and created_at

#### Scenario: Fetch a full compare by id
- **WHEN** a caller requests compare id `7`
- **THEN** the `compare_runs` row is returned with all its `eval_runs` and each run's per-criterion `eval_criteria_results`
- **AND** each run carries its snapshotted `prompt_name`, `prompt_type`, and `draft_text`

#### Scenario: History survives prompt deletion
- **WHEN** a prompt named in a stored compare is deleted after the compare ran
- **THEN** `get_compare` still returns the run with its `prompt_name`, `prompt_type`, and `draft_text` intact (snapshotted, no FK)

### Requirement: Compare CLI
The system SHALL provide `python -m src.eval.compare` mirroring `src/eval/run.py`, accepting `--contract-type`, `--rubric`, `--task`, `--prompts` (comma-separated names), `--mode drafter-only`, `--n` (drafts per prompt), and `--list-compares`. It SHALL print the per-criterion matrix and the run-level pass counts, and persist the compare to the DB.

#### Scenario: Run a compare from the CLI
- **WHEN** `python -m src.eval.compare --contract-type sale --rubric contract_sale_v1 --task "…" --prompts draft_sale,draft_sale_v2 --n 1` runs
- **THEN** the compare executes, is persisted, and the matrix is printed with a `DB compare id` line

#### Scenario: List compares from the CLI
- **WHEN** `python -m src.eval.compare --list-compares` runs
- **THEN** recent compares are printed (id, label, rubric, n_drafts, scored_at)

### Requirement: Reuse of the Existing Judge
The compare orchestration SHALL evaluate drafts by calling `src/eval/scoring.py::evaluate_contract` unchanged. `src/eval/scoring.py`, `src/eval/judge.py`, and `src/eval/rubric.py` SHALL NOT be modified by this change.

#### Scenario: The judge path is unchanged
- **WHEN** a compare evaluates a draft
- **THEN** it calls `evaluate_contract(contract_text, rubric_name, task_desc)` and the returned dict shape is identical to a standalone eval run
