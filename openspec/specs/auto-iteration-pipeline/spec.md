# auto-iteration-pipeline Specification

## Purpose
Close the loop between stored drafting runs and future clause selection: after each run, learn from reviewer rejections, auto-reject custom clauses at a configurable threshold, persist the outcome, and never let the learn node break the pipeline.

## Requirements
### Requirement: Auto-iteration pipeline runs learn node after store
The system SHALL provide an `auto_pipeline_run` that extends the standard pipeline with a learn node executed after the store node.

#### Scenario: Pipeline with learn node
- **WHEN** `auto_pipeline_run` is invoked
- **THEN** the graph executes `generate -> fill -> evaluate -> check -> (improve)* -> store -> learn -> END`

#### Scenario: Standard pipeline unchanged
- **WHEN** `pipeline_run` is invoked
- **THEN** the graph executes `generate -> fill -> evaluate -> check -> (improve)* -> store -> END` with no learn node

### Requirement: Learn node aggregates rejection recommendations
The system SHALL aggregate `clause_review` recommendations with `action='reject'` from both the current run and recent historical runs.

#### Scenario: Aggregate current and historical
- **WHEN** learn node runs for contract_type='employment'
- **THEN** it counts rejections from the current run's recommendations PLUS the last 50 historical pipeline_runs of the same contract_type

### Requirement: Auto-reject custom clauses at threshold
The system SHALL automatically mark custom clauses as rejected when accumulated rejection count reaches `AUTO_REJECT_THRESHOLD` (default 3).

#### Scenario: Clause reaches threshold
- **WHEN** clause_id=7263 has 2 current + 2 historical = 4 rejections (>= 3)
- **AND** clause 7263 is a custom clause
- **THEN** system calls `bulk_review(7263, 'rejected')` setting all tag_review dims to "rejected"

#### Scenario: Below threshold skipped
- **WHEN** clause has only 2 total rejections (< 3)
- **THEN** system does NOT reject it

### Requirement: Only custom clauses are rejected
The system SHALL verify a clause is a custom clause before auto-rejecting; base and tagged clauses are never modified.

#### Scenario: Base clause skipped
- **WHEN** clause_id refers to a base clause (tags.source='base')
- **THEN** system skips rejection even if threshold is met

### Requirement: Learn results persisted to pipeline_runs
The system SHALL record auto-applied rejections in the `learn_applied` JSONB column of the stored pipeline_run row.

#### Scenario: learn_applied written
- **WHEN** learn node rejects clauses 7263 and 7264
- **THEN** pipeline_runs.learn_applied contains `[{clause_id:7263,...}, {clause_id:7264,...}]`

### Requirement: Fail-safe learn node
The system SHALL catch all exceptions in the learn node so it never crashes the pipeline.

#### Scenario: bulk_review fails
- **WHEN** `bulk_review` raises an exception for a clause
- **THEN** that clause is skipped, the error is swallowed, and the pipeline continues

### Requirement: learn_applied returned in tool result
The `auto_pipeline_run` MCP tool SHALL return a `learn_applied` field listing auto-rejected clauses.

#### Scenario: Tool returns learn_applied
- **WHEN** `auto_pipeline_run` completes
- **THEN** result includes `learn_applied: [{clause_id, total_count, current_count, historical_count}]`

### Requirement: Configurable threshold
The rejection threshold SHALL be configurable via the `AUTO_REJECT_THRESHOLD` environment variable.

#### Scenario: Custom threshold
- **WHEN** `AUTO_REJECT_THRESHOLD=5` is set in the environment
- **THEN** clauses need 5+ accumulated rejections to be auto-rejected
