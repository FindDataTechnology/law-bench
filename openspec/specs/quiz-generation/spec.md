# quiz-generation Specification

## Purpose
Generate a natural-language quiz from an assembled contract: extract every slot, ask one question per slot, and carry slot metadata so answers can be mapped back deterministically.

## Requirements
### Requirement: Extract all slots from assembled contract
The system SHALL extract ALL `{{slot}}` placeholders from the assembled contract body text. The extraction SHALL use the existing `src.docs.slots.extract_slots()` function. The system SHALL also retrieve slot instructions (name, label, description, example) from the assembly result.

#### Scenario: Extract slots from contract with 15 placeholders
- **WHEN** the assembled contract body contains 15 `{{slot}}` patterns
- **THEN** the system SHALL return a list of 15 unique slot names
- **THEN** each slot SHALL be paired with its instruction metadata (if available)

#### Scenario: Contract with no slots
- **WHEN** the assembled contract has no `{{slot}}` patterns
- **THEN** the system SHALL return an empty slot list
- **THEN** the quiz generation step SHALL be skipped (no quiz needed)

### Requirement: Generate natural-language question per slot
The system SHALL use an LLM (configured via `QUIZ_MODEL` in `.env`) to generate a natural-language question for each slot. The prompt SHALL include the slot name, label, description, example, contract type, and scenario. The output SHALL be a list of `{slot, question, required: true}` items.

#### Scenario: Generate question for delivery_address slot
- **WHEN** the slot is `delivery_address` with label "交货地点" and description "The location where goods shall be delivered"
- **THEN** the LLM SHALL generate a question like "Where should the goods be delivered? Please provide the full address."

#### Scenario: Generate question for penalty_rate slot
- **WHEN** the slot is `penalty_rate` with example "0.05"
- **THEN** the LLM SHALL generate a question that includes context about typical ranges, e.g., "What daily penalty rate should apply for late delivery? (e.g., 0.05% per day)"

### Requirement: Enforce full slot coverage
The system SHALL present ALL slots as required fields in the quiz form. The frontend SHALL validate that every slot has a non-empty value before allowing submission. The backend SHALL verify that all expected slots are present in the submitted answers.

#### Scenario: Frontend validates all slots filled
- **WHEN** the quiz form has 10 slots and the user has filled 9
- **THEN** the submit button SHALL be disabled
- **THEN** the unfilled slot SHALL be visually highlighted

#### Scenario: Backend verifies slot coverage
- **WHEN** the frontend submits answers with all 10 slots filled
- **THEN** the backend SHALL verify that all 10 expected slot names are present in the answers dict
- **THEN** if any slot is missing, the backend SHALL reject the submission and request completion

### Requirement: Quiz items include slot metadata for context
Each quiz item SHALL include the original slot name alongside the generated question. This allows the user to see both the human-readable question and the technical slot identifier.

#### Scenario: Quiz item shows slot name and question
- **WHEN** the quiz form renders a quiz item
- **THEN** the display SHALL show the generated question as the label
- **THEN** the slot name SHALL be available as a tooltip or secondary text for reference
