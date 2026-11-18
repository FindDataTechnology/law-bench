# copilotkit-frontend Specification

## Purpose
Wire the React frontend to the LangGraph agent with CopilotKit: provider setup, chat sidebar, live agent state, and human-in-the-loop surfaces for quiz filling, review triage, and contract preview.

## Requirements
### Requirement: CopilotKit provider setup
The Next.js app SHALL wrap the entire application in a `CopilotKit` provider with `runtimeUrl` pointing to the backend API route and `agent` set to the review agent name.

#### Scenario: Provider wraps app
- **WHEN** the app loads
- **THEN** the `CopilotKit` provider SHALL be initialized with `runtimeUrl="/api/copilotkit"` and `agent="contract-review-agent"`
- **THEN** all child components SHALL have access to `useAgent()` and `useHumanInTheLoop()` hooks

### Requirement: Chat sidebar with CopilotSidebar
The app SHALL render a `CopilotSidebar` component for chat interaction with the agent. The sidebar SHALL be docked to the right side of the screen and collapsible.

#### Scenario: Chat sidebar visible
- **WHEN** the app loads
- **THEN** a chat sidebar SHALL be visible on the right side
- **THEN** the user SHALL be able to type messages and receive agent responses
- **THEN** the sidebar SHALL be collapsible to give more space to the state panel

### Requirement: State panel with useAgent hook
The app SHALL render a custom state panel that uses the `useAgent()` hook to read `agent.state` and display real-time progress, review cards, and metrics. The panel SHALL update automatically when `copilotkit_emit_state` is called from the backend.

#### Scenario: State panel shows progress
- **WHEN** the backend calls `copilotkit_emit_state` with updated `node_timings` and `current_stage`
- **THEN** the state panel SHALL re-render to show the latest progress
- **THEN** completed nodes SHALL show ✅ with duration
- **THEN** the current node SHALL show ⏳ or a spinner

#### Scenario: State panel shows reviews
- **WHEN** the review panel node completes and emits state with `reviews` array
- **THEN** the state panel SHALL render review cards for each reviewer
- **THEN** each card SHALL show the reviewer name, model, lens, and suggestions

### Requirement: Quiz form with useHumanInTheLoop
The app SHALL register a `useHumanInTheLoop` hook for the `"fill_contract_slots"` interrupt. The hook SHALL render a `QuizForm` component that displays all slot questions and validates full coverage before allowing submission.

#### Scenario: Quiz form renders on interrupt
- **WHEN** the backend calls `interrupt({"name": "fill_contract_slots", "quiz_items": [...]})`
- **THEN** the `useHumanInTheLoop` hook SHALL detect the matching interrupt name
- **THEN** the `QuizForm` component SHALL render in the chat or state panel
- **THEN** each quiz item SHALL display as a required input field

#### Scenario: Quiz form validates and submits
- **WHEN** the user fills all required fields
- **THEN** the submit button SHALL become enabled
- **THEN** upon clicking submit, `respond(values)` SHALL be called
- **THEN** the graph SHALL resume with the submitted values

### Requirement: Review triage with useHumanInTheLoop
The app SHALL register a `useHumanInTheLoop` hook for the `"triage_reviews"` interrupt. The hook SHALL render a review triage component where the user can accept/reject/modify each suggestion.

#### Scenario: Review triage renders
- **WHEN** the backend calls `interrupt({"name": "triage_reviews", "suggestions": [...]})`
- **THEN** a triage form SHALL render with all suggestions
- **THEN** each suggestion SHALL have an accept/reject toggle and an editable text field

### Requirement: Contract preview with useHumanInTheLoop
The app SHALL register a `useHumanInTheLoop` hook for the `"approve_final_contract"` interrupt. The hook SHALL render a contract preview component with approve/edit/abort options.

#### Scenario: Contract preview renders
- **WHEN** the backend calls `interrupt({"name": "approve_final_contract", "contract_text": "..."})`
- **THEN** a contract preview SHALL render showing the full contract text
- **THEN** the user SHALL be able to click "Approve & Export", "Request Edits", or "Abort"

### Requirement: Metrics dashboard
The state panel SHALL include a metrics section showing total duration, model call count, total tokens, estimated cost, and suggestion acceptance rate. These metrics SHALL be read from `agent.state.node_timings`, `agent.state.model_calls`, etc.

#### Scenario: Metrics dashboard displays
- **WHEN** the graph completes and final state is emitted
- **THEN** the metrics section SHALL show:
  - Total time: sum of all node timings
  - Model calls: count of entries in `model_calls`
  - Total tokens: sum of all token counts
  - Est. cost: sum of all costs
  - Suggestion acceptance rate: `len(suggestions_applied) / len(review_suggestions)`

### Requirement: API route proxy to backend
The Next.js app SHALL have an API route at `/api/copilotkit` that proxies requests to the Python backend using `LangGraphHttpAgent`.

#### Scenario: API route proxies to backend
- **WHEN** the frontend sends a request to `/api/copilotkit`
- **THEN** the route SHALL forward the request to the Python backend at `http://localhost:8000/`
- **THEN** the response SHALL be streamed back to the frontend
