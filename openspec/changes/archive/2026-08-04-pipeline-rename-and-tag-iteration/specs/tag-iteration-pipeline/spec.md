## ADDED Requirements

### Requirement: Tag iteration suggest pipeline
The system SHALL provide a `tag_iteration_suggest` pipeline that analyzes failed evaluations and suggests tag modifications.

#### Scenario: Suggest tag changes
- **WHEN** a contract evaluation fails
- **THEN** the system analyzes failing clauses and suggests tag modifications via LLM
- **AND** returns a list of suggestions with clause_id, current_tags, suggested_tags, and reason

#### Scenario: Read-only operation
- **WHEN** `tag_iteration_suggest` runs
- **THEN** it SHALL NOT modify any clause tags
- **AND** it SHALL be safe to run concurrently with other pipelines

### Requirement: Tag iteration apply pipeline
The system SHALL provide a `tag_iteration_apply` pipeline that applies approved tag suggestions and validates the result.

#### Scenario: Apply approved suggestions
- **WHEN** user provides approved tag suggestions
- **THEN** the system saves original tags for rollback
- **AND** applies the new tags to clauses
- **AND** re-generates and re-evaluates the contract
- **AND** returns the new evaluation score

#### Scenario: Auto-rollback on score degradation
- **WHEN** the new evaluation score is lower than the original
- **THEN** the system SHALL automatically rollback to original tags
- **AND** return the rollback status

#### Scenario: Advisory lock for concurrency
- **WHEN** `tag_iteration_apply` runs
- **THEN** it SHALL acquire a PostgreSQL advisory lock
- **AND** block other `tag_iteration_apply` calls until completion
- **AND** release the lock on completion (success or failure)

### Requirement: LLM tag suggestion logic
The system SHALL use LLM to analyze clause content and suggest appropriate tags.

#### Scenario: Analyze failing clauses
- **WHEN** suggest_retag node runs
- **THEN** it SHALL identify clauses involved in failing criteria
- **AND** call LLM with clause content, current tags, and failure reasons
- **AND** receive suggestions for tag modifications

#### Scenario: Suggest all tag types
- **WHEN** LLM suggests tags
- **THEN** it MAY suggest changes to any tag type: scenario, stance, strength, risk, mandatory
- **AND** each suggestion SHALL include a reason explaining the change

### Requirement: Rollback mechanism
The system SHALL support rolling back tag changes if validation fails.

#### Scenario: Save original tags
- **WHEN** applying tag suggestions
- **THEN** the system SHALL save the original tags before modification
- **AND** store them in pipeline state for potential rollback

#### Scenario: Restore original tags
- **WHEN** rollback is triggered
- **THEN** the system SHALL restore all clauses to their original tags
- **AND** log the rollback event
