## Context

This project builds a multi-agent system for drafting Chinese legal contracts. The requirements are:
- Use `uv` to initialize the Python project
- Use CrewAI for agent orchestration
- Multiple agents with different roles, each with a configurable model
- Run models on Volcengine Ark's OpenAI-compatible `/api/plan/v3` endpoint
- Per-role model selection via environment variables
- Specialized for Chinese-language legal contract drafting

## Goals / Non-Goals

**Goals:**
- Implement three specialized agents with clear Chinese legal drafting roles
- Allow per-role model configuration via `.env` without code changes
- Use model families from different vendors for drafter/auditor to reduce correlated hallucinations
- Deliver a working sequential pipeline that produces a drafted contract from a user prompt
- Provide seed templates for common Chinese contract types
- Provide a SQLite store of evaluation rubrics (seeded from harbor) extensible with local contract rubrics

**Non-Goals:**
- Full RAG retrieval over the entire body of Chinese statutory law (can be added later)
- Persistent storage of drafted contract outputs (user can manage manually; note: persistent storage of evaluation *rules* as reference data is in-scope - see Decision 7)
- Wiring the auditor to evaluate drafts against stored rubrics, and runtime storage of evaluation results (deferred - the rules DB ships as a reference store)
- Web UI or interactive CLI chat beyond what CrewAI provides
- Free-form open debate between agents (deferred until sequential pipeline is validated)
- Dedicated editor agent (deferred if self-revision proves insufficient)

## Decisions

### 1. Project management: use `uv`
**Choice:** `uv init` to create the project, manage dependencies with `uv`.
**Rationale:** Explicitly requested by the user. `uv` is faster and more reliable than pip for modern Python projects.
**Alternatives considered:** Poetry, pip — rejected per request.

### 2. Agent topology: 3 agents, drafter self-revises
**Choice:**
- `Intake Clarifier`: extracts structured request from user's natural language
- `Drafter`: writes initial draft
- `Auditor`: independently reviews for legal issues, cites errors
- `Drafter` revises once based on auditor's feedback (no separate editor)
**Rationale:** A dedicated editor can cause voice/style drift between drafter and editor. A single drafter that incorporates feedback maintains consistent formal Chinese tone. Can add a dedicated editor later if self-revision is consistently poor.
**Alternatives considered:** 4-agent pipeline (intake → draft → audit → edit) — YAGNI for v1.

### 3. Model provider: treat Ark as OpenAI-compatible
**Choice:** Use LiteLLM's `openai/` provider with custom `OPENAI_API_BASE` pointing to `https://ark.cn-beijing.volces.com/api/plan/v3`. No special Ark/Volcengine adapter.
**Rationale:** Ark's `/plan/v3` endpoint implements OpenAI's wire protocol natively. Using the built-in `openai/` provider avoids any adapter-specific bugs.
**Alternatives considered:** LiteLLM's native `volcengine/` provider — simpler to use the OpenAI compatibility layer since the endpoint already speaks it.

### 4. Model assignment: cross-family diversity
**Choice (configurable via `.env`, default):**
- **Intake**: `openai/deepseek-v4-flash` — fast, cheap, sufficient for 中文 Q&A clarification
- **Drafter**: `openai/doubao-seed-2-0-pro` — ByteDance's native model, strong performance on formal Chinese legal prose
- **Auditor**: `openai/glm-5.2` — Zhipu's model, different model family from Doubao, independent review catches blind spots
**Rationale:** Drafter and auditor from different families avoid correlated hallucinations (they won't both miss the same error in 法条 citation). This is more important than "best model" for both roles.
**Alternatives considered:** Same family for both — risks mutual agreement on bad legal citations. All different per role — unnecessary, increases API key/configuration complexity.

### 5. Configuration: all settings via environment variables
**Choice:**
- Provider API key goes to `OPENAI_API_KEY` (LiteLLM/CrewAI reads this automatically)
- `OPENAI_API_BASE` for the Ark endpoint
- `{ROLE}_MODEL`, `{ROLE}_TEMPERATURE`, `{ROLE}_MAX_TOKENS` for per-role configuration
- `.env` (gitignored) for real values, `.env.example` (committed) for placeholders
**Rationale:** Users can swap models, adjust temperature, and change endpoints without any code changes. Secrets stay out of version control.
**Alternatives considered:** Config file (YAML/TOML) — env vars are simpler for a small project, no extra dependency needed.

### 6. Orchestration: CrewAI sequential process
**Choice:** `Process.sequential` — tasks execute in order, output of one becomes input to the next. No manager agent.
**Rationale:** We have a fixed, known pipeline. Hierarchical process with a manager adds unnecessary overhead and non-determinism for this use case.
**Alternatives considered:** `Process.hierarchical` — unnecessary for a fixed three-step+revison flow.

### 7. Evaluation rules store: SQLite mirroring harbor's Rubric model
**Choice:** A single tracked SQLite file at `db/evaluation_rules.db` with two tables: `rubrics` (id, name, context, source, source_path, description, created_at) and `criteria` (id, rubric_id FK, name, description, guidance, ordinal, `UNIQUE(rubric_id, name)`). Seeded with harbor's two rubrics and their 13 criteria. An idempotent script `scripts/extract_harbor_rules.py` discovers the installed harbor package dir via `uv tool dir` + glob, reads its two TOML rubric files (`cli/quality_checker/default-rubric.toml`, `analyze/prompts/analyze-rubric.toml`) with stdlib `tomllib`, and upserts the reference rows with provenance (`source = harbor:v0.20.0`, `source_path`, `context`). The schema is open to locally-authored contract rubrics (`source = 'local'`, `context = 'contract'`); re-extraction never touches `local` rows.
**Rationale:** Harbor does not store rubrics in a database; they are TOML files loaded at runtime by `load_rubric()`. So we are not mirroring harbor's DB; we are materializing harbor's TOML rubrics into SQLite for queryability and future extension. Parsing TOML with stdlib `tomllib` by path avoids coupling this project to the harbor install (no `import harbor`, no added dependency). The schema mirrors harbor's `Rubric` / `RubricCriterion` / `QualityCheckModel` so the store stays structurally compatible if harbor's LLM-as-judge pattern is wired up later.
**Alternatives considered:** (a) Importing harbor and reusing `load_rubric()` for guaranteed fidelity; rejected to avoid adding harbor as a dependency and coupling to its isolated uv-tool env. (b) Tracking the seed as SQL/TOML and generating the SQLite into `output/` (gitignored); rejected for v1 in favor of a single tracked DB, revisit if binary diffs in git become noisy. (c) Adding runtime `evaluations` / `evaluation_criteria_results` tables now; deferred as out of scope for a reference store, the schema is designed to accept them later.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| Model IDs provided for Ark endpoint may be incorrect (version suffixes sometimes differ) | Code fails loudly on startup with a clear error if model is not found; user can correct the name in `.env` easily |
| Drafter may fail to properly incorporate all auditor feedback | We'll ship with self-revision and observe. If it fails consistently, we can add a dedicated editor agent in a follow-up change. |
| No statutory RAG → auditor may hallucinate 法条 citations | Start without RAG — for boilerplate contracts that cite general 民法典 provisions, prompt-based works acceptably well. Add `RagTool` over a corpus of common statutes if citations are consistently wrong. |
| Single round of revision may not resolve all issues | Set a hard limit of one revision round to avoid infinite loops. Users can manually kick off another round if needed. Extending to multiple automated rounds is trivial later. |
| Harbor install path drifts across versions (e.g. `python3.12` -> `python3.13`) | The extraction script discovers the harbor package directory via `uv tool dir` + glob rather than hardcoding the path; fails with a clear error if harbor is not installed |
| Harbor rubrics are about benchmark task design, not contract drafting | Stored as read-only reference rows (`source = 'harbor:v0.20.0'`); they are a structural template, not contract-evaluation rules. Local contract rubrics are authored separately under `source = 'local'` |

## Open Questions

- What specific contract types to seed in the template library? This can be decided after the skeleton pipeline is working — any additional types just add new template files, no architecture changes needed.
- Should the auditor consume contract rubrics from the rules DB to evaluate drafts? Deferred for now; the DB ships as a reference store. If wanted, add an `evaluation-rules` consumer requirement and a wiring task in a follow-up.
