> Implementation note: built with CrewAI's YAML-driven `@CrewBase` pattern (`src/config/agents.yaml`, `src/config/tasks.yaml`, `src/crew.py`, `main.py`) instead of the programmatic `src/agents.py`/`src/tasks.py` originally listed. Task 7.3 wires template content into the drafter's context. All capabilities below are delivered and verified (crew assembles; a prior run produced `output/employee-nda.md`).

## 1. Project Setup

- [x] 1.1 Initialize Python project with `uv init`
- [x] 1.2 Add dependencies: `crewai` and `python-dotenv`
- [x] 1.3 Create `.gitignore` (includes `.env`)
- [x] 1.4 Create `.env` with the user's Ark endpoint, key, and model configuration
- [x] 1.5 Create `.env.example` with placeholder values

## 2. Core Structure

- [x] 2.1 Create `src/` directory structure
- [x] 2.2 Implement `src/llm.py`: helper to create LLM instance from environment variables per role
- [x] 2.3 Verify environment variable loading fails loudly on missing required vars

## 3. Agent Implementation

- [x] 3.1 Implement `src/agents.py`: define three agents (intake_clarifier, drafter, auditor) with proper Chinese backstory and goals
- [x] 3.2 Verify each agent gets LLM from `llm.py` with role-specific config

## 4. Task Implementation

- [x] 4.1 Implement `src/tasks.py`: define four tasks (clarify_requirements, draft_contract, audit_contract, revise_contract)
- [x] 4.2 Set up proper context passing between tasks: output of previous becomes context for next

## 5. Crew Orchestration

- [x] 5.1 Implement `src/crew.py`: assemble the crew with sequential process
- [x] 5.2 Configure the sequential flow: clarify → draft → audit → revise

## 6. Entry Point

- [x] 6.1 Implement `src/main.py`: CLI entry point that accepts user's request and kicks off the crew
- [x] 6.2 Print the final revised contract output to console

## 7. Templates

- [x] 7.1 Create `templates/` directory
- [x] 7.2 Add seed templates for 2 common Chinese contract types (e.g., 服务协议, 保密协议)
- [x] 7.3 Ensure drafter can reference templates in its context

## 8. Evaluation Rules Database

- [x] 8.1 Create `db/` directory and SQLite schema (`rubrics`, `criteria` tables with `UNIQUE(rubric_id, name)`)
- [x] 8.2 Implement `scripts/extract_harbor_rules.py`: discover harbor package dir via `uv tool dir` + glob; parse `default-rubric.toml` and `analyze-rubric.toml` with stdlib `tomllib`; idempotently upsert reference rows with provenance (`source = harbor:v0.20.0`, `source_path`, `context`)
- [x] 8.3 Run extraction; verify 2 rubrics and 13 criteria seeded (task_quality: 11, trial_behavior: 2)
- [x] 8.4 Verify re-running the script is idempotent (no duplicate rows; `local` rows untouched)
- [x] 8.5 (Optional) Author one sample local contract rubric (`source = local`, `context = contract`) to validate the open schema
