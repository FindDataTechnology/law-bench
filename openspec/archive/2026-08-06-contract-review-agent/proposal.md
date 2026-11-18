## Why

The existing self-heal pipeline (`generate → fill → evaluate → improve`) uses a single model for drafting and a single judge for evaluation. This creates a ceiling: the judge (kimi-k3) is structurally unreliable — it confuses contracts with rubrics, misreads fields, and bounds the eval score. There is no multi-perspective review, no human-in-the-loop for slot filling, no runtime observability, and no way to see per-node timing or model costs. A multi-model review agent with human checkpoints would catch issues a single judge misses, let humans fill critical business slots directly, and provide full observability into agent execution.

## What Changes

- **New `contract-review-agent` standalone service** — a FastAPI + LangGraph agent with CopilotKit middleware that orchestrates a multi-model contract refinement pipeline
- **Multi-model review panel** — 3 configurable reviewer models (defined in `.env`) each analyze the draft from a different lens (legal accuracy, commercial fairness, completeness) in parallel
- **Suggestion synthesis** — merge reviewer suggestions, deduplicate conflicts, present unified edit recommendations
- **Quiz generation** — extract ALL `{{slot}}` placeholders from the assembled contract, generate natural-language questions for each, present as a form where humans must fill every field
- **Three human checkpoints** — CP1: triage reviewer suggestions (accept/reject/modify); CP2: fill quiz/slots (all required); CP3: final contract approval before export
- **Dual evaluation** — final contract evaluated with both existing rubric-based eval (criterion PASS/FAIL) AND deepeval metrics (hallucination, faithfulness, slot relevance)
- **New `agent_runs` table** — per-node timing, model calls with token usage/cost/latency, review suggestions, slot coverage stats, eval linkage
- **New MCP tools** — `agent_run_store`, `agent_run_get`, `agent_run_list` for agent metrics
- **New HTTP endpoints** — `/agent-runs/*` on the law-bench API for metrics access
- **Next.js frontend** — CopilotKit chat sidebar + state panel showing real-time progress, review cards, quiz form, contract preview, and metrics dashboard

## Capabilities

### New Capabilities
- `review-panel`: Multi-model parallel review with configurable models/lenses from .env, streaming state to frontend via copilotkit_emit_state
- `quiz-generation`: Extract all slots from assembled contract, generate natural-language questions per slot, enforce full coverage (all slots must be filled)
- `human-checkpoints`: Three LangGraph interrupt() checkpoints (triage reviews, fill quiz, final approval) bridged to CopilotKit useHumanInTheLoop
- `dual-evaluation`: Combine existing rubric eval (criterion PASS/FAIL) with deepeval metrics (hallucination, faithfulness, slot relevance) for final contract
- `agent-metrics`: New agent_runs table + MCP tools + HTTP endpoints for per-node timing, model calls, token usage, costs, review quality, slot coverage
- `copilotkit-frontend`: Next.js app with CopilotKit chat + state panel + quiz form + contract preview + metrics dashboard

### Modified Capabilities
<!-- No existing specs need modification — this is a new standalone service that imports law-bench internals -->

## Impact

- **New service**: `contract-review-agent/` directory with Python backend + Next.js frontend
- **New DB table**: `agent_runs` in the shared PostgreSQL database
- **New MCP tools**: 3 tools added to `fd-coding-law-bench-mcp` for agent metrics
- **New HTTP routes**: `/agent-runs/*` on the law-bench API
- **Dependencies**: Add `copilotkit` (Python SDK), `ag-ui-langgraph` to the agent's pyproject.toml; frontend adds `@copilotkit/react-core`, `@copilotkit/runtime`
- **Shared modules**: Agent imports `src.eval.*`, `src.clauses.*`, `src.docs.*` directly (no MCP protocol overhead)
- **Environment**: New `.env` vars for reviewer models/lenses, quiz model, CopilotKit URL
- **No breaking changes**: Existing pipelines, APIs, and MCP tools are untouched
