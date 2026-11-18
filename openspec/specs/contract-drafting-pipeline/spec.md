# contract-drafting-pipeline Specification

## Purpose
Draft Chinese contracts through a sequential multi-role LLM pipeline with per-role model configuration, Ark endpoint wiring, template-driven generation, and secrets kept out of git.

## Requirements
### Requirement: Per-role Model Configuration
The system SHALL allow the model name, temperature, and max tokens for each agent role to be configured via environment variables.

#### Scenario: Configure model for drafter role
- **WHEN** user sets `DRAFTER_MODEL` in `.env`
- **THEN** the drafter agent uses that model
- **WHEN** user sets `DRAFTER_TEMPERATURE` and `DRAFTER_MAX_TOKENS`
- **THEN** the drafter agent uses those settings

#### Scenario: Start with missing required environment variable
- **WHEN** a required environment variable (e.g., `DRAFTER_MODEL`) is not set
- **THEN** the application fails loudly on startup with a clear error message

### Requirement: Sequential Pipeline Flow
The system SHALL execute the contract drafting pipeline in a fixed sequential order:
1. Intake Clarifier → 2. Drafter → 3. Auditor → 4. Drafter revises based on audit

#### Scenario: Complete pipeline execution
- **WHEN** user provides a natural language request to draft a contract
- **THEN** Intake Clarifier produces a structured description of the requested contract with all key metadata
- **THEN** Drafter writes an initial full draft contract
- **THEN** Auditor independently reviews the draft and produces a report of issues, missing clauses, and incorrect legal citations
- **THEN** Drafter revises the draft to address the auditor's issues
- **THEN** the final revised draft is output to the user

### Requirement: Role Specialization
Each agent SHALL have a distinct, well-defined role aligned with Chinese legal contract drafting:

1. **Intake Clarifier**: Interprets the user's natural language request, extracts the contract type, parties, key terms, and any special requirements.
2. **Drafter**: Writes a complete, formally worded Chinese legal contract draft based on the structured request.
3. **Auditor**: Reviews the draft independently, flags legal risks, ensures 法条 citations are correct, and identifies missing mandatory clauses.

#### Scenario: Specialized roles produce appropriate outputs
- **WHEN** pipeline runs for "create a service agreement between A and B"
- **THEN** Intake Clarifier outputs structured metadata: type = service agreement, party A = [name], party B = [name]
- **THEN** Drafter outputs a complete draft agreement with properly numbered sections in formal Chinese legal language
- **THEN** Auditor outputs a list of specific issues (e.g., "missing limitation of liability clause", "民法典 citation incorrect")

### Requirement: Volcengine Ark Endpoint
The system SHALL connect to Volcengine Ark at the configured `OPENAI_API_BASE` endpoint using the configured `OPENAI_API_KEY`.

#### Scenario: Connect to Ark endpoint
- **WHEN** `OPENAI_API_BASE` is set to `https://ark.cn-beijing.volces.com/api/plan/v3`
- **THEN** all model requests are routed to this endpoint using OpenAI-compatible wire protocol

### Requirement: Gitignore Secrets
`.env` containing API keys and secrets SHALL be excluded from version control via `.gitignore`. A `.env.example` with placeholder values SHALL be committed.

#### Scenario: New clone setup
- **WHEN** user clones the repository
- **THEN** they can copy `.env.example` to `.env` and fill in their own values with no missing placeholders

### Requirement: Contract Templates
The system SHALL support loading seed templates for common Chinese contract types to guide the drafter.

#### Scenario: Load seed template
- **WHEN** user requests a contract of a type that has a seed template
- **THEN** the drafter uses the template structure to guide drafting, preserving standard clauses

### Requirement: Python Project Management
The project SHALL use `uv` for dependency management. Dependencies SHALL include `crewai` and `python-dotenv`.

#### Scenario: Install dependencies
- **WHEN** user runs `uv sync`
- **THEN** all required dependencies are installed correctly

