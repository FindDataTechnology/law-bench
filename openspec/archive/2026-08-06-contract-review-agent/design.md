## Context

The law-template project has a mature contract generation pipeline (`self_heal_pipeline`) that generates, fills, evaluates, and self-heals contracts. It uses a single drafter model and a single judge model. The judge (kimi-k3) is structurally unreliable — it confuses contracts with rubrics, asks for PASS/FAIL in contract text, and misreads fields. This bounds the eval score ceiling.

The project already has:
- FastMCP server (`fd-coding-law-bench-mcp`) with 30+ tools for contract generation, evaluation, clause management, RAG search
- FastAPI HTTP API wrapping MCP tools for contract content, batch generation, catalog, tags
- deepeval integration via `GPTModel` pointed at Volcengine Ark endpoint
- LangGraph pipelines (self-heal, auto-reject, tag-iteration) with `PipelineState` TypedDict
- PostgreSQL database with `pipeline_runs`, `eval_runs`, `fill_cache`, `clauses` tables
- Shared Python modules: `src.eval.*`, `src.clauses.*`, `src.docs.*`
- Main web UI on port 8010 (Jinja2 + evaluation rules management)
- MCP HTTP API on port 8000 (contract generation)

There is NO timing/metrics infrastructure. No `perf_counter`, no Prometheus, no request timing middleware. The only temporal data are `created_at` timestamps on DB rows.

## Goals / Non-Goals

**Goals:**
- Build a standalone multi-model review agent that generates a contract, sends it to 3 configurable reviewer models, synthesizes suggestions, generates a quiz for humans to fill ALL slots, produces a final contract, and evaluates it
- Three human-in-the-loop checkpoints: CP1 (triage reviews), CP2 (fill quiz/slots), CP3 (final approval)
- Real-time frontend showing per-node progress, review cards, quiz form, contract preview, and metrics
- Per-node timing, model call tracking (tokens, cost, latency), review quality metrics, slot coverage stats
- Reuse existing law-bench internals (direct Python imports, not MCP protocol)
- Add new MCP tools and HTTP endpoints for agent metrics to law-bench-mcp

**Non-Goals:**
- Replacing the existing self-heal pipeline — the review agent is a separate service
- Adding streaming token-by-token output — state-level streaming via `copilotkit_emit_state` is sufficient
- Multi-tenant support — single-user for now
- Modifying existing rubric criteria or evaluation logic — the agent uses existing eval as-is
- Building a mobile app — web-only frontend

## Decisions

### 1. Standalone service vs extending existing MCP server
**Decision**: New standalone `contract-review-agent/` directory with its own FastAPI + Next.js.
**Rationale**: The review agent has fundamentally different UX (chat + state panel + quiz form) vs the existing MCP server (REST API). CopilotKit middleware requires specific FastAPI integration. Keeping it separate avoids polluting the existing MCP server. The agent imports `src.*` modules directly — no MCP protocol overhead.
**Alternatives considered**: Adding CopilotKit to existing MCP API (rejected: different concerns, different deployment); building as MCP tool only (rejected: no frontend, no checkpoints).

### 2. Direct Python imports vs MCP protocol for law-bench integration
**Decision**: Direct Python imports (`from src.eval.run import evaluate_contract`).
**Rationale**: Same repo, same venv, same DB. MCP protocol adds serialization overhead and async complexity for no benefit. The agent is an internal consumer, not an external one.
**Alternatives considered**: MCP client (rejected: overhead, complexity); HTTP API calls (rejected: need to add endpoints for everything, latency).

### 3. LangGraph `interrupt()` vs custom checkpoint mechanism
**Decision**: Use LangGraph's native `interrupt()` + `Command(resume=...)` with `PostgresSaver` checkpointer.
**Rationale**: Built-in persistence, resume capability, and CopilotKit bridges this to the frontend via `useHumanInTheLoop`. No need to invent a custom mechanism.
**Alternatives considered**: Custom WebSocket-based checkpoint (rejected: reinventing the wheel, no persistence).

### 4. CopilotKit `useHumanInTheLoop` for quiz form
**Decision**: Use `useHumanInTheLoop` hook with a custom `QuizForm` component that validates all slots are filled before calling `respond()`.
**Rationale**: CopilotKit's HITL mechanism is designed exactly for this — agent calls `interrupt()`, frontend renders a form, user fills it, `respond()` resumes the graph. The frontend enforces full slot coverage.
**Alternatives considered**: Custom state-based form (rejected: more complex, no graph pause/resume); separate page for quiz (rejected: breaks chat flow).

### 5. Three reviewers with different lenses
**Decision**: 3 reviewers defined in `.env`, each with a model + lens (legal_accuracy, commercial_fairness, completeness).
**Rationale**: Different lenses prevent convergence on the same feedback. Legal reviewer catches missing required elements; commercial reviewer catches unfair terms; completeness reviewer catches missing sections/slots.
**Alternatives considered**: 3 identical reviewers with different prompts (rejected: less diversity); single reviewer with multi-pass (rejected: slower, less diverse).

### 6. Dual evaluation (rubric + deepeval)
**Decision**: Run both existing rubric eval (criterion PASS/FAIL) AND deepeval metrics (hallucination, faithfulness, slot relevance).
**Rationale**: Rubric eval checks structural completeness (are all required sections present?). Deepeval checks content quality (did the filler hallucinate terms? are slot values contextually appropriate?). Together they cover both structure and content.
**Alternatives considered**: Rubric only (rejected: no content quality check); deepeval only (rejected: lose existing criterion-level PASS/FAIL).

### 7. `agent_runs` table for metrics
**Decision**: New PostgreSQL table with JSONB columns for node_timings, model_calls, review_suggestions, deepeval_scores.
**Rationale**: JSONB gives flexibility for evolving metrics without schema changes. Links to existing `eval_runs` via FK. Separate from `pipeline_runs` because the review agent has different fields (reviewer suggestions, slot coverage, quiz items).
**Alternatives considered**: Extending `pipeline_runs` (rejected: different schema, different purpose); separate metrics DB (rejected: over-engineering, same Postgres is fine).

### 8. Next.js frontend with CopilotKit
**Decision**: Next.js app with `CopilotKit` provider, `CopilotSidebar` for chat, custom `useAgent` panel for state/progress, `useHumanInTheLoop` for checkpoints.
**Rationale**: CopilotKit's LangGraph integration is purpose-built for this pattern. Bidirectional state sync via `copilotkit_emit_state` + `agent.setState()`. Real-time progress updates. Built-in HITL support.
**Alternatives considered**: Plain React (rejected: no CopilotKit integration); Vue/Svelte (rejected: CopilotKit React-only); separate chat + dashboard (rejected: CopilotKit sidebar + panel is cleaner).

## Risks / Trade-offs

**[Judge unreliability persists]** → The review agent uses the same judge for final eval. Mitigation: the 3-reviewer panel catches issues the judge misses; dual eval (rubric + deepeval) provides redundant checks. The agent doesn't depend on the judge for correctness — it depends on the review panel.

**[CopilotKit is a new dependency]** → Adds `@copilotkit/react-core`, `@copilotkit/runtime`, Python `copilotkit` SDK. Mitigation: CopilotKit is open-source, well-maintained, and specifically designed for LangGraph integration. If it fails, we can replace the frontend without touching the agent backend.

**[3 parallel LLM calls increase cost/latency]** → Each review panel call costs ~3x a single eval. Mitigation: models are configurable in `.env` — users can use cheaper models for reviewers. Streaming state shows progress so it doesn't feel slow. The review panel runs in parallel, not sequentially.

**[Quiz generation quality]** → LLM-generated questions may be unclear or miss context. Mitigation: questions include slot instructions (name, label, description, example) as context. Users can see the original slot name alongside the question. Future: allow users to edit questions before filling.

**[PostgresSaver checkpoint bloat]** → Every interrupt saves full state to Postgres. Mitigation: checkpoints are small (text + JSON). Add periodic cleanup job if needed. The `agent_runs` table provides a cleaner audit trail.

**[Direct imports couple agent to src.* internals]** → If `src.eval.*` or `src.clauses.*` change, the agent breaks. Mitigation: these are internal modules in the same repo. Changes are visible in PRs. The agent is an internal consumer, not an external one.
