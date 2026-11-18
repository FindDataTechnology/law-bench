# admin-assistant-web — Delta Spec

## Purpose

Adds an admin-only floating AI assistant to the law-bench workbench: a chat bubble that expands into a conversational panel which drives law-bench capabilities (contract generation, evaluation, rubric/prompt/clause reads, RAG search) through the law-bench MCP server, with strict admin gating and no destructive tools.

## ADDED Requirements

### Requirement: Admin-only entry point
The workbench SHALL render the assistant entry point (floating chat bubble and its scripts) only for sessions whose token grants the `admin` scope. Sessions without the `admin` scope (including anonymous visitors) SHALL receive no assistant markup, scripts, or entry point.

#### Scenario: Admin sees the bubble
- **WHEN** a logged-in user whose token includes the `admin` scope loads any workbench page
- **THEN** the floating chat bubble is rendered and can be expanded into the chat panel

#### Scenario: Non-admin sees nothing
- **WHEN** a logged-in user whose token lacks the `admin` scope loads any workbench page
- **THEN** no assistant markup or scripts are present in the page

### Requirement: Admin-gated chat API
The assistant chat endpoint SHALL only accept requests that pass the workbench's admin scope check (same fail-closed mechanism as other managed routes). Chat traffic SHALL flow through the workbench's own same-origin proxy; the chat runtime service SHALL NOT be a publicly reachable alternative path to assistant functionality.

#### Scenario: Unauthenticated request is rejected
- **WHEN** a request without a valid session reaches the assistant chat endpoint
- **THEN** it is rejected without invoking the chat runtime

#### Scenario: Non-admin request is rejected
- **WHEN** a valid session lacking the `admin` scope reaches the assistant chat endpoint
- **THEN** it is rejected with a denial response and the chat runtime is not invoked

#### Scenario: Admin request is proxied
- **WHEN** a valid admin-scope session sends a chat message
- **THEN** the request is proxied to the chat runtime and the assistant's reply is returned to the same page

### Requirement: Destructive tools excluded
The assistant SHALL NOT be able to invoke delete tools (`clause_delete`, `rubric_delete`, `criterion_delete`, `prompt_delete`) or any other tool on the assistant connection's denylist. Deletion requests made in conversation SHALL NOT change any stored data.

#### Scenario: Delete request does not delete
- **WHEN** an admin asks the assistant to delete a rubric or clause
- **THEN** no deletion is performed and the stored rubric/clause remains unchanged

#### Scenario: Non-destructive work still available
- **WHEN** an admin asks the assistant to search clauses, generate a contract, or evaluate a draft
- **THEN** the assistant performs the task using the corresponding MCP tools

### Requirement: Floating conversational surface
The assistant SHALL present as a floating chat bubble available on workbench pages; expanding it opens a chat panel where the admin converses in natural language and the assistant streams replies. The bubble SHALL be collapsible and SHALL NOT obstruct page function when collapsed.

#### Scenario: Expand and converse
- **WHEN** an admin clicks the floating bubble
- **THEN** a chat panel opens, accepts a natural-language message, and streams the assistant's reply in place

#### Scenario: Collapse restores the page
- **WHEN** an admin collapses the chat panel
- **THEN** the page is fully usable and only the bubble remains

### Requirement: Graceful degradation
When the chat runtime, the MCP server, or the LLM backend is unavailable, the assistant SHALL surface a clear error in the chat panel and the rest of the workbench SHALL remain fully functional.

#### Scenario: Runtime down
- **WHEN** the chat runtime is unreachable and an admin opens the chat panel
- **THEN** the panel reports the assistant as unavailable and every other workbench page works normally
