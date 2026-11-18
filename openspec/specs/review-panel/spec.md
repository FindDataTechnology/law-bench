# review-panel Specification

## Purpose
Run multiple reviewer models in parallel with configurable lens-specific prompts and stream their progress to the frontend for triage.

## Requirements
### Requirement: Configurable reviewer models from environment
The system SHALL load reviewer configurations from `.env` file at startup. Each reviewer SHALL have a model identifier, a lens (review perspective), and a display name. The system SHALL support at least 3 concurrent reviewers.

#### Scenario: Load reviewers from .env
- **WHEN** the agent starts and reads `.env` containing `REVIEWER_1_MODEL`, `REVIEWER_1_LENS`, `REVIEWER_1_NAME` (and 2, 3)
- **THEN** the system SHALL construct a list of 3 reviewer configs with model, lens, and name fields

#### Scenario: Missing reviewer config
- **WHEN** `.env` is missing required reviewer fields (e.g., `REVIEWER_2_MODEL` not set)
- **THEN** the system SHALL raise a startup error with a clear message listing the missing variables

### Requirement: Parallel multi-model review execution
The system SHALL execute all reviewer models in parallel against the same draft contract. Each reviewer SHALL receive the draft text, the contract type, the scenario (from tags), and its assigned lens. Each reviewer SHALL return a list of suggestions with severity (critical/warning/info), the affected section, and a recommended change.

#### Scenario: Three reviewers run in parallel
- **WHEN** the review panel node executes with 3 configured reviewers
- **THEN** all 3 LLM calls SHALL be dispatched concurrently via `asyncio.gather()`
- **THEN** each call SHALL receive the same draft but different lens-specific prompts
- **THEN** results SHALL be collected into a `reviews` list with timing per reviewer

#### Scenario: Reviewer returns suggestions
- **WHEN** a reviewer model analyzes a draft with a missing delivery address clause
- **THEN** the reviewer SHALL return a suggestion with `severity: "critical"`, `section: "delivery"`, `recommendation: "Add delivery address and method clauses"`

### Requirement: Streaming review progress to frontend
The system SHALL call `copilotkit_emit_state()` after each reviewer completes, pushing partial results to the frontend. The emitted state SHALL include the list of completed reviews, the total review count, and the current stage name.

#### Scenario: Frontend sees reviews appear one by one
- **WHEN** reviewer 1 completes at t=3s, reviewer 2 at t=5s, reviewer 3 at t=8s
- **THEN** the frontend SHALL receive 3 state updates showing `completed_reviews` incrementing from 1 to 2 to 3
- **THEN** each update SHALL include the newly completed reviewer's suggestions

### Requirement: Reviewer lens-specific prompts
Each reviewer lens SHALL use a distinct system prompt that focuses the model's analysis on that perspective. Legal accuracy SHALL check for missing required elements and legal soundness. Commercial fairness SHALL check for balanced risk allocation and reasonable terms. Completeness SHALL check for all required sections and proper slot definitions.

#### Scenario: Legal reviewer catches missing clause
- **WHEN** the legal reviewer analyzes a sale contract missing the inspection period clause
- **THEN** the legal reviewer SHALL flag this as a critical suggestion referencing the missing legal requirement

#### Scenario: Commercial reviewer catches unfair term
- **WHEN** the commercial reviewer analyzes a contract with 0.1%/day penalty rate
- **THEN** the commercial reviewer SHALL flag this as a warning suggesting reduction to market-standard 0.05%/day
