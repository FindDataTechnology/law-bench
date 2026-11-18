## 1. Project Scaffolding

- [x] 1.1 Create `contract-review-agent/` directory structure: `agent/`, `agent/nodes/`, `api/`, `frontend/`
- [x] 1.2 Create `contract-review-agent/pyproject.toml` with dependencies: fastapi, uvicorn, langgraph, langchain-core, copilotkit, ag-ui-langgraph, python-dotenv, psycopg
- [x] 1.3 Create `contract-review-agent/.env.example` with all required env vars (REVIEWER_1/2/3_MODEL, REVIEWER_1/2/3_LENS, REVIEWER_1/2/3_NAME, QUIZ_MODEL, DATABASE_URL, OPENAI_API_KEY, OPENAI_API_BASE, COPILOTKIT_URL)
- [x] 1.4 Create `contract-review-agent/README.md` with setup instructions, architecture overview, and how to run

## 2. Database Schema

- [x] 2.1 Create SQL migration for `agent_runs` table: id, thread_id, contract_type, tags (JSONB), node_timings (JSONB), model_calls (JSONB), review_suggestions (JSONB), suggestions_applied (JSONB), total_slots, human_filled_slots, eval_run_id (FK to eval_runs), deepeval_scores (JSONB), total_duration, created_at
- [x] 2.2 Add migration script to apply the schema change to the shared PostgreSQL database
- [x] 2.3 Create Python CRUD functions for agent_runs: `insert_agent_run()`, `get_agent_run()`, `list_agent_runs()` in `contract-review-agent/agent/store.py`

## 3. Agent State and Graph

- [x] 3.1 Create `contract-review-agent/agent/state.py` with `ReviewState` TypedDict containing all fields: contract_type, tags, task_desc, draft_v1, slots, instructions, reviewers, reviews, completed_reviews, total_reviews, synthesized_suggestions, accepted_suggestions, quiz_items, slot_values, draft_v2, eval_result, deepeval_scores, node_timings, model_calls, total_duration, current_stage
- [x] 3.2 Create `contract-review-agent/agent/checkpointer.py` with `AsyncPostgresSaver` setup using DATABASE_URL from .env
- [x] 3.3 Create `contract-review-agent/agent/graph.py` with `build_review_graph()` function that assembles all nodes and edges: START → generate_v1 → review_panel → synthesize → human_triage (interrupt) → generate_quiz → human_quiz (interrupt) → generate_v2 → evaluate → human_review (interrupt) → export → END
- [x] 3.4 Compile the graph with the PostgresSaver checkpointer

## 4. Agent Nodes — Generation and Review

- [x] 4.1 Create `contract-review-agent/agent/nodes/generate_v1.py`: import `src.clauses.assemble.assemble_contract()` and `src.docs.slots.extract_slots()`, generate draft v1, extract all slots and instructions, record timing
- [x] 4.2 Create `contract-review-agent/agent/nodes/review_panel.py`: load 3 reviewers from .env, execute all 3 in parallel via `asyncio.gather()`, each with lens-specific prompt, call `copilotkit_emit_state()` after each completes, record per-reviewer timing and token usage
- [x] 4.3 Create `contract-review-agent/agent/nodes/synthesize.py`: merge suggestions from all 3 reviewers, deduplicate conflicts, produce unified `synthesized_suggestions` list with source attribution
- [x] 4.4 Create lens-specific review prompts: legal_accuracy prompt checks missing required elements and legal soundness; commercial_fairness prompt checks balanced risk allocation and reasonable terms; completeness prompt checks all required sections and proper slot definitions

## 5. Agent Nodes — Quiz and Human Checkpoints

- [x] 5.1 Create `contract-review-agent/agent/nodes/generate_quiz.py`: for each slot in the assembled contract, use QUIZ_MODEL to generate a natural-language question incorporating the slot's instruction (name, label, description, example), produce `quiz_items` list with slot name, question, and required flag
- [x] 5.2 Create `contract-review-agent/agent/nodes/human_triage.py`: call `interrupt()` with synthesized suggestions, wait for user to accept/reject/modify each suggestion, return `accepted_suggestions`
- [x] 5.3 Create `contract-review-agent/agent/nodes/human_quiz.py`: call `interrupt()` with quiz_items, wait for user to fill ALL slots, validate that every required slot has a non-empty value, return `slot_values` dict
- [x] 5.4 Create `contract-review-agent/agent/nodes/human_review.py`: call `interrupt()` with final draft_v2, wait for user to approve or request changes, return approval status

## 6. Agent Nodes — Generation v2, Evaluation, and Export

- [x] 6.1 Create `contract-review-agent/agent/nodes/generate_v2.py`: re-assemble contract applying accepted suggestions and human-provided slot_values, produce final draft_v2 text
- [x] 6.2 Create `contract-review-agent/agent/nodes/evaluate.py`: run existing rubric eval via `src.eval.scoring.evaluate_contract()`, run deepeval metrics (HallucinationMetric, FaithfulnessMetric, custom GEval for slot relevance), combine results into `eval_result` and `deepeval_scores`
- [x] 6.3 Create `contract-review-agent/agent/nodes/export.py`: generate DOCX/PDF via existing `contract_generate()` tool with format parameter, store artifact, return download URL
- [x] 6.4 Create `contract-review-agent/agent/nodes/metrics.py`: after all nodes complete, aggregate node_timings, model_calls, total_duration, slot coverage stats, call `insert_agent_run()` to persist metrics

## 7. FastAPI Backend with CopilotKit

- [x] 7.1 Create `contract-review-agent/api/main.py`: FastAPI app with CORS middleware, import graph from `agent.graph`, set up CopilotKit middleware
- [x] 7.2 Create `contract-review-agent/api/copilotkit.py`: configure `LangGraphAGUIAgent` wrapping the review graph, add AG-UI endpoint via `add_langgraph_fastapi_endpoint()`
- [x] 7.3 Create `contract-review-agent/api/config.py`: Pydantic BaseSettings loading all env vars (reviewer configs, database URL, OpenAI credentials, server host/port)
- [x] 7.4 Add startup event to initialize PostgresSaver checkpointer and verify DB connection
- [x] 7.5 Add health check endpoint at `/health`

## 8. Law-Bench MCP Tools for Agent Metrics

- [x] 8.1 Create `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/tools/agent_metrics.py` with `agent_run_store` MCP tool: accept thread_id, contract_type, tags, node_timings, model_calls, review_suggestions, suggestions_applied, total_slots, human_filled_slots, eval_run_id, deepeval_scores, total_duration; INSERT into agent_runs table; return run_id
- [x] 8.2 Add `agent_run_get` MCP tool: accept run_id, SELECT full row from agent_runs, return as dict
- [x] 8.3 Add `agent_run_list` MCP tool: accept optional limit (default 20), SELECT recent runs with summary fields (id, contract_type, total_duration, n_passed, all_pass, created_at), return as list
- [x] 8.4 Register the new tool module in `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/server.py`

## 9. Law-Bench HTTP Routes for Agent Metrics

- [x] 9.1 Create `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/api/routes/agent_runs.py` with router: POST `/agent-runs` (store), GET `/agent-runs/{run_id}` (get), GET `/agent-runs` (list)
- [x] 9.2 Add Pydantic request/response schemas in `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/api/schemas.py`: `AgentRunStoreRequest`, `AgentRunResponse`, `AgentRunListResponse`
- [x] 9.3 Register the agent_runs router in `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/api/main.py`

## 10. Frontend Scaffolding

- [x] 10.1 Initialize Next.js app in `contract-review-agent/frontend/` with TypeScript, Tailwind CSS, App Router
- [x] 10.2 Install CopilotKit dependencies: `@copilotkit/react-core`, `@copilotkit/runtime`, `@copilotkit/react-ui`
- [x] 10.3 Create `frontend/src/app/layout.tsx` with CopilotKit provider wrapping the app, runtimeUrl pointing to backend `/api/copilotkit`
- [x] 10.4 Create `frontend/src/app/api/copilotkit/route.ts` with `LangGraphHttpAgent` pointing to Python backend URL
- [x] 10.5 Create `frontend/src/app/page.tsx` with two-column layout: CopilotSidebar on left, state panel on right

## 11. Frontend Components — Chat and State Panel

- [x] 11.1 Create `frontend/src/components/chat.tsx`: wrap CopilotSidebar with agentId="contract-review-agent", configure labels and styling
- [x] 11.2 Create `frontend/src/components/state-panel.tsx`: use `useAgent()` hook to read `agent.state`, display current_stage, node_timings as a progress list with ✅/⏳/🚦 indicators, show completed_reviews/total_reviews
- [x] 11.3 Create `frontend/src/components/metrics-panel.tsx`: display total_duration, model_calls count, total tokens, estimated cost, slot coverage (human_filled/total)

## 12. Frontend Components — Human Checkpoints UI

- [x] 12.1 Create `frontend/src/components/review-triage.tsx`: use `useHumanInTheLoop()` with name="triage_reviews", render cards for each synthesized suggestion with accept/reject toggles, call `respond()` with accepted_suggestions on submit
- [x] 12.2 Create `frontend/src/components/quiz-form.tsx`: use `useHumanInTheLoop()` with name="fill_contract_slots", render input fields for each quiz_item, validate all required fields are filled before enabling submit, call `respond()` with slot_values
- [x] 12.3 Create `frontend/src/components/contract-preview.tsx`: use `useHumanInTheLoop()` with name="approve_final_contract", render markdown preview of draft_v2, show eval scores, provide approve/edit buttons, call `respond()` with approval status

## 13. Integration and Testing

- [x] 13.1 Create end-to-end test script that starts the Python backend, starts the Next.js frontend, triggers a full agent run via the chat UI, and verifies all 3 checkpoints are hit
- [x] 13.2 Test review panel with 3 different models, verify parallel execution and streaming state updates
- [x] 13.3 Test quiz generation with a sale contract, verify all slots are extracted and questions are generated
- [x] 13.4 Test human checkpoints: verify interrupt() pauses the graph, frontend renders the form, respond() resumes execution
- [x] 13.5 Test dual evaluation: verify both rubric eval and deepeval metrics run and results are stored
- [x] 13.6 Test agent metrics: verify agent_runs table is populated with correct timings, model calls, and slot coverage
- [x] 13.7 Test error handling: verify missing .env vars produce clear errors, LLM call failures are caught and reported
