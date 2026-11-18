## MODIFIED Requirements

### Requirement: Pipeline renamed to self_heal_pipeline_run
The system SHALL expose the standard contract generation pipeline as `self_heal_pipeline_run` (renamed from `pipeline_run`).

#### Scenario: Call renamed pipeline
- **WHEN** user calls `self_heal_pipeline_run(contract_type="sale", stance="balanced")`
- **THEN** system executes generate → fill → evaluate → check → [improve]* → store → END

#### Scenario: Backward compatibility
- **WHEN** user calls old name `pipeline_run`
- **THEN** system SHALL raise error directing user to use `self_heal_pipeline_run`

### Requirement: Pipeline documentation
The system SHALL include clear docstring explaining:
- Purpose: single contract generation with self-healing loop
- Concurrency: safe to run in parallel (read-only on clauses table)
- Nodes: generate, fill, evaluate, check, improve, store
