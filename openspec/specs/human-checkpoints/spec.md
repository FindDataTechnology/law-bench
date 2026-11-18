# human-checkpoints Specification

## Purpose
Insert explicit human approval gates into the LangGraph drafting flow (triage, quiz/slot filling, final approval) using interrupt(), with checkpoint state that survives resume.

## Requirements
### Requirement: CP1 — Triage reviewer suggestions
The system SHALL pause the graph after suggestion synthesis and present all reviewer suggestions to the user. The user SHALL be able to accept, reject, or modify each suggestion. The graph SHALL resume only after the user submits their triage decisions.

#### Scenario: User accepts some suggestions, rejects others
- **WHEN** the review panel produces 5 suggestions (2 critical, 2 warning, 1 info)
- **THEN** the frontend SHALL render a triage form with all 5 suggestions
- **THEN** the user SHALL be able to check/uncheck each suggestion
- **THEN** the user SHALL be able to edit the text of accepted suggestions
- **THEN** upon clicking "Continue", the graph SHALL resume with the accepted/modified suggestions

#### Scenario: User accepts all suggestions
- **WHEN** the user clicks "Accept All"
- **THEN** all suggestions SHALL be marked as accepted
- **THEN** the graph SHALL resume with all suggestions applied

### Requirement: CP2 — Fill quiz/slots
The system SHALL pause the graph after quiz generation and present the quiz form to the user. The user SHALL fill in ALL slot values. The graph SHALL resume only after all required slots are filled and submitted.

#### Scenario: User fills all slots and submits
- **WHEN** the quiz form displays 10 required slots
- **THEN** the user SHALL fill in all 10 fields
- **THEN** the submit button SHALL become enabled
- **THEN** upon clicking "Submit All Answers", the graph SHALL resume with the slot values

#### Scenario: User attempts to submit with empty slots
- **WHEN** the user has filled 8 of 10 slots
- **THEN** the submit button SHALL remain disabled
- **THEN** the unfilled slots SHALL be visually indicated as required

### Requirement: CP3 — Final contract approval
The system SHALL pause the graph after final contract generation and present the complete contract to the user for review. The user SHALL be able to approve the contract for export, request edits, or abort.

#### Scenario: User approves final contract
- **WHEN** the user reviews the generated contract and clicks "Approve & Export"
- **THEN** the graph SHALL resume and proceed to the export node
- **THEN** the export node SHALL generate DOCX/PDF files

#### Scenario: User requests edits
- **WHEN** the user clicks "Request Edits" and provides feedback
- **THEN** the graph SHALL resume and route back to the generate_v2 node with the feedback
- **THEN** a new draft SHALL be generated incorporating the feedback

### Requirement: LangGraph interrupt() mechanism
All checkpoints SHALL use LangGraph's native `interrupt()` function with a `PostgresSaver` checkpointer. The interrupt payload SHALL include all data needed by the frontend to render the appropriate form. Resumption SHALL use `Command(resume=value)`.

#### Scenario: Graph pauses at interrupt
- **WHEN** a node calls `interrupt({"name": "fill_contract_slots", "quiz_items": [...]})`
- **THEN** the graph execution SHALL pause
- **THEN** the checkpointer SHALL save the full state to PostgreSQL
- **THEN** the interrupt payload SHALL be surfaced to the frontend via CopilotKit

#### Scenario: Graph resumes after interrupt
- **WHEN** the frontend calls `respond(values)` via `useHumanInTheLoop`
- **THEN** CopilotKit SHALL send `Command(resume=values)` to the backend
- **THEN** the graph SHALL resume from the checkpoint
- **THEN** the `interrupt()` call SHALL return the resumed values

### Requirement: Checkpoint state tracking
The system SHALL track which checkpoint is currently active in the agent state. The `current_stage` field SHALL be updated before each interrupt to indicate which checkpoint the user is at.

#### Scenario: Frontend shows current checkpoint
- **WHEN** the graph reaches CP2 (quiz filling)
- **THEN** `current_stage` SHALL be set to `"human_quiz"`
- **THEN** the frontend state panel SHALL display "Checkpoint 2: Fill Contract Details"
