# add-admin-copilot-assistant

## Why

The workbench's core capabilities (contract generation, rubric/eval management, clause curation, RAG search) are already wrapped as 37 MCP tools, but admins have no conversational entry point for them — every task requires navigating pages and forms. A floating chat assistant on the website turns the MCP server into a natural-language admin console. CopilotKit is the natural framework: its self-hosted runtime natively bridges a web chat UI to MCP servers over streamable HTTP, and CopilotKit is already in the ecosystem (contract-review-agent frontend).

## What Changes

- Add an admin-only floating chat assistant (CopilotKit `CopilotPopup`) to the law-bench workbench website. Non-admin sessions never see the entry point and cannot reach the chat API.
- Add a small React island (Vite build) to the Jinja2/vanilla-JS frontend; the island script is emitted into `src/web/static` and conditionally included by `base.html` for admin sessions only.
- Add a same-origin FastAPI proxy route (`/copilotkit/*`) gated by the existing `require_scope("admin")`, forwarding chat traffic to a self-hosted CopilotKit runtime (Node) that stays cluster-internal on the cheap-box k3s cluster.
- The CopilotKit runtime connects to the law-bench FastMCP server over streamable HTTP (token-guarded) via `createMCPClient`, and to the existing LLM provider (GLM/DeepSeek OpenAI-compatible endpoints) via the OpenAI adapter.
- The FastMCP server gains a tool-exclusion setting so the assistant-facing deployment never advertises destructive tools: `clause_delete`, `rubric_delete`, `criterion_delete`, `prompt_delete`. Existing stdio/other clients are unaffected (default: no exclusions).
- Deploy the runtime as a new container alongside the review backend (new Dockerfile + k3s manifests, runbook updated).

Non-goals: the assistant never exposes delete tools; this does not replace contract-review-agent (separate app, separate spec `copilotkit-frontend`).

## Capabilities

### New Capabilities
- `admin-assistant-web`: The floating AI assistant surface on the workbench — admin-only visibility and API gating, the `/copilotkit/*` proxy, MCP tool scope (no destructive tools), chat session behavior, and failure modes.

### Modified Capabilities
- `law-bench-mcp`: New requirement — the MCP server SHALL support excluding a configured set of tools from advertisement (tool denylist), so an assistant-facing deployment can hide destructive tools while other clients keep the full toolset.

## Impact

- **Code**: `src/web/` (base.html conditional include, new proxy route, static assets); new Vite island project (TypeScript/React, location per design); `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/server.py` (tool exclusion).
- **New service**: CopilotKit runtime (Node) — new Dockerfile, k3s deployment on cheap-box, `deploy/cheap-box/README.md` runbook section.
- **Dependencies**: `@copilotkit/react-core`, `@copilotkit/react-ui`, `@copilotkit/runtime`, Vite + React toolchain (first frontend build chain in the Python repo).
- **Config/env**: LLM endpoint + key for the runtime; MCP server URL + token for the streamable HTTP connection; denial list values.
- **Risk surface**: the chat can trigger expensive operations (compare runs, contract generation) and mutations (tag iteration, clause review) — destructive deletes stay excluded; mutation tools remain available to admins (they are admins in the existing RBAC model).
