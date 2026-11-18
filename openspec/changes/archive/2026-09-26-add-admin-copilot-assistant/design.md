# add-admin-copilot-assistant — Design

## Context

The workbench is a server-rendered FastAPI + Jinja2 app (`src/web`) with no frontend build chain. Authorization is Logto-scope based (`src/web/auth/`): the token's `scope` claim is checked by `require_scope`, and `admin` expands to the `*` wildcard. The FastMCP server (`fd-coding-law-bench-mcp`) wraps 37 tools over `src.*`, runs stdio by default and streamable HTTP when `MCP_HTTP_TRANSPORT=http`, behind an ASGI `_TokenGuard` that rejects requests lacking the shared token. Deployment is the cheap-box k3s cluster (`deploy/cheap-box/README.md`), which already hosts the review backend as a second service. CopilotKit is already used in the ecosystem for the contract-review-agent Next.js app (spec `copilotkit-frontend`); its self-hosted runtime supports connecting to remote MCP servers, and streamable-HTTP MCP support landed 2026-07 (CopilotKit issue #2319, closed).

See proposal.md for motivation and the delta specs for behavior requirements.

## Goals / Non-Goals

**Goals:**
- One admin-gated, same-origin path from the workbench to a chat runtime that can call the MCP tools.
- The runtime and the MCP HTTP instance stay cluster-internal; the public surface is only the workbench.
- Delete tools are structurally absent from the assistant's toolset (not advertised at all), enforced at the MCP server.
- Frontend footprint is a single built island (JS + CSS), no framework migration of existing pages.

**Non-Goals:**
- Replacing contract-review-agent or integrating with its CopilotKit setup.
- Server-side chat history persistence (history lives in the widget for the browser session).
- Exposing the assistant to non-admin roles or tuning per-role tool scopes.
- Rate limiting/quota beyond what the workbench already applies globally (can be added later).

## Decisions

### D1 — CopilotKit self-hosted runtime as a Node sidecar; React island in the Jinja site

The island is a small Vite + React project rendering `CopilotPopup`, built to static assets that `base.html` includes conditionally. The runtime (`@copilotkit/runtime`) is a separate Node service.

- Why not browser-direct MCP: the browser cannot orchestrate tool calls without holding an LLM key; also every tool would be exposed client-side.
- Why not hand-rolling the agent loop in FastAPI: CopilotKit supplies the popup UI, streaming protocol, tool-loop, and MCP client; the user chose CopilotKit and it is already in the ecosystem.
- Why not LibreChat/Open WebUI/Dify: standalone apps or heavyweight platforms, not an embeddable floating widget.
- Island location: new repo-root `assistant-ui/` (matches the repo's pattern of sibling toolchain dirs like `fd-coding-law-bench-mcp/`, `contract-review-agent/frontend/`); Vite emits to `src/web/static/assistant/` so FastAPI serves the assets and nothing under `src/` needs node_modules to build the Python package.

### D2 — Enforcement point: FastAPI reverse proxy with `require_scope("admin")`

A new `/copilotkit/*` route in `src/web` proxies to the runtime's cluster-internal address (`http://copilot-runtime.<ns>.svc:port`).

- The proxy is the only public path; the runtime gets a ClusterIP Service with no Ingress. This keeps a single authorization point with the existing fail-closed semantics — no second IdP integration inside the runtime.
- The proxy must stream (`httpx` stream → `StreamingResponse`): CopilotKit speaks a streaming protocol, and tool calls such as `compare_run` can run for minutes — no response buffering, timeouts raised accordingly.
- Alternatives rejected: exposing the runtime publicly with JWT validation inside CopilotKit (duplicates Logto integration in a service with thin auth hooks); ingress-level cookie gating (ingress cannot validate Logto sessions).

### D3 — Tool exclusion at the MCP server (`MCP_TOOL_DENYLIST`)

`server.py` drops denylisted tools before serving, on both transports; the assistant's MCP HTTP instance runs with `MCP_TOOL_DENYLIST=clause_delete,rubric_delete,criterion_delete,prompt_delete`. Other deployments (gateway, stdio) run unchanged with the full toolset — if the existing gateway-exposed instance shares a process, the assistant gets its own instance so denylist scope stays per-deployment.

- Why server-side rather than filtering in the runtime's `createMCPClient`: exclusion at the source is structural (the tools are never advertised or invocable), survives runtime misconfiguration, and is testable in the MCP project's own suite.
- The connection authenticates with the existing `_TokenGuard` shared token; the runtime's MCP client passes it as a request header (MCP TypeScript SDK transports accept custom headers).

### D4 — LLM via the runtime's OpenAI adapter against the existing provider

`OpenAIAdapter` with a custom base URL pointed at the GLM/DeepSeek OpenAI-compatible endpoint; key and model configured as env on the runtime deployment. Both providers support OpenAI function calling, which the tool loop requires. No new LLM contract.

### D5 — Assistant instance of the MCP server, not the gateway path

The assistant connects to a dedicated MCP HTTP instance (same image/code, dedicated container + port + token + denylist env). This isolates assistant traffic (its own failure domain and logs) from other MCP clients and keeps the denylist from leaking to clients that need delete tools.

## Risks / Trade-offs

- [New frontend build chain in a Python repo] → The island is isolated in `assistant-ui/` with its own lockfile; CI builds it before the Docker image; `src/` never sees node_modules.
- [New always-on Node service to operate] → Follow the review-backend pattern (dedicated Dockerfile, k3s manifests, runbook section); the runtime is stateless, rollback is re-pointing the proxy or scaling down.
- [Admin chat can trigger expensive operations (`compare_run`, contract generation)] → These are the same operations admins can trigger from the UI today; per-conversation cost is visible in the panel; quota/rate limiting deferred (non-goal).
- [Non-delete mutations (clause review status, tag iteration, prompt/rubric create/update) are available in chat] → Accepted: admins hold these powers via the existing RBAC; deletes are the irreversible category and are excluded.
- [CopilotKit runtime/version churn] → Pin the runtime package version; the AG-UI/MCP integration surface used here is narrow (popup + MCP client + one adapter).
- [37 tools in one model loop can degrade tool selection] → Mitigate with the assistant's system prompt scoping typical tasks; if selection quality suffers, split by tool tags (`contracts`/`rubrics`/`eval`/...) per conversation mode. Deferred until observed.

## Migration Plan

1. Land the MCP server denylist feature (default no-op) and the assistant MCP HTTP instance.
2. Deploy the CopilotKit runtime (ClusterIP, no ingress) with LLM/MCP env; smoke-test `/health` in-cluster.
3. Land the FastAPI proxy + island behind the existing RBAC; roll the workbench.
4. Rollback: remove the island include (single template flag) and scale down the runtime + assistant MCP instance; no data migration involved, nothing persisted.

## Open Questions

- Exact provider/model for the assistant loop (GLM vs DeepSeek) — resolved at deploy time via env; both are compatible, pick per cost/latency.
