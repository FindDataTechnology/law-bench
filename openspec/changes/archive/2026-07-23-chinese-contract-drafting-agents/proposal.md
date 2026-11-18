## Why

Chinese legal contract drafting requires different levels of reasoning and quality from different roles: fast clarification, strong formal Chinese writing, independent adversarial review. A single model can't leverage the complementary strengths of different model families, and needs a configurable pipeline that swaps models without code changes.

This change creates a CrewAI-based multi-agent system for drafting Chinese contracts using Volcengine Ark as the model provider, with per-role model selection controlled via environment variables.

## What Changes

- Initialize a new Python project managed by `uv`
- Add `crewai` and `python-dotenv` dependencies
- Implement three specialized agents with distinct roles:
  1. **Intake Clarifier** — clarifies user's requirements, extracts contract metadata (parties, type, key terms)
  2. **Drafter** — writes full contract draft using seed templates and legal conventions
  3. **Auditor** — independently reviews the draft for legal risks, incorrect 法条 citations, and missing clauses
- Drafter revises once based on auditor feedback (no separate editor agent to start)
- Models for each role are read from `.env` — supports any OpenAI-compatible model available on Volcengine Ark
- Example seed templates for common contract types
- Extract harbor's evaluation rubrics into a SQLite database in the project:
  - Store harbor's two default rubrics (task quality, trial behavior) and their 13 criteria with provenance
  - Schema mirrors harbor's `Rubric` / `RubricCriterion` model and is open to locally-authored contract rubrics
  - Idempotent extraction script reads harbor's installed TOML rubric files by path (no `import harbor`)

## Capabilities

### New Capabilities
- `contract-drafting-pipeline`: Multi-agent sequential pipeline for drafting Chinese legal contracts with independent auditing
- `evaluation-rules`: SQLite store of evaluation rubrics and criteria, seeded from harbor's rubrics, extensible with local contract rubrics

### Modified Capabilities
- (None)

## Impact

- New Python project at project root
- New `src/` directory with agent, task, and crew definitions
- New `templates/` directory for contract templates
- Dependencies: `crewai`, `python-dotenv` (LiteLLM is a transitive dependency of CrewAI)
- `.env` configuration for API keys and model selection
- New `db/` directory with a tracked SQLite database (`evaluation_rules.db`) of rubrics and criteria
- New `scripts/extract_harbor_rules.py` for idempotent extraction; no new runtime dependencies (uses stdlib `tomllib`)
