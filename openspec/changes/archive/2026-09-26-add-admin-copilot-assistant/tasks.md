# add-admin-copilot-assistant — Tasks

## 1. MCP server tool denylist

- [x] 1.1 Add `MCP_TOOL_DENYLIST` parsing (comma-separated tool names) and tool removal before serving in `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/server.py`, effective on both stdio and HTTP transports; unset/empty keeps the full toolset
- [x] 1.2 Add tests: denylisted tools absent from tool listing, denylisted tool call fails as unknown tool, default start advertises all tools
- [x] 1.3 Add a smoke test that the HTTP app (`MCP_HTTP_TRANSPORT=http` + `_TokenGuard`) serves with the denylist applied and rejects requests without the shared token

## 2. Assistant MCP HTTP instance (deployment)

- [x] 2.1 Add container/manifest for the assistant MCP instance (same image, dedicated service/port, shared token env, `MCP_TOOL_DENYLIST=clause_delete,rubric_delete,criterion_delete,prompt_delete`), ClusterIP only
- [x] 2.2 Update `deploy/cheap-box/README.md` runbook with the assistant MCP instance (env, port, token rotation note)

## 3. CopilotKit runtime service

- [x] 3.1 Create `Dockerfile.copilot-runtime` (Node slim, pinned `@copilotkit/runtime`) with a `/health` endpoint check
- [x] 3.2 Implement the runtime entrypoint: `CopilotRuntime` with `OpenAIAdapter` (base URL/model/key from env) and `createMCPClient` connecting to the assistant MCP instance over streamable HTTP with the shared token header, denylist re-checked client-side as defense in depth
- [x] 3.3 Add k3s manifests (Deployment + ClusterIP Service, no Ingress) with env for LLM endpoint/key/model, MCP URL, MCP token
- [x] 3.4 Smoke-test in-cluster: health check, one MCP tool round-trip through the runtime with a test prompt

## 4. FastAPI proxy route

- [x] 4.1 Add `/copilotkit/*` proxy route in `src/web` gated by `require_scope("admin")`, streaming `httpx` → `StreamingResponse`, no buffering, extended timeouts
- [x] 4.2 Add tests: unauthenticated and non-admin requests rejected before reaching the runtime; admin request proxied and streamed back
- [x] 4.3 Add runtime URL env/config plumbing (`src/settings.py` or app config) with a clear error when unset

## 5. React island (assistant-ui)

- [x] 5.1 Scaffold `assistant-ui/` (Vite + React + TypeScript, pinned `@copilotkit/react-core`/`@copilotkit/react-ui`), building a single JS + CSS bundle into `src/web/static/assistant/`
- [x] 5.2 Implement `CopilotPopup` island: runtime URL from same-origin `/copilotkit`, zh labels (site i18n context), streaming replies, collapsible bubble
- [x] 5.3 Wire build into CI/Docker (build island before the workbench image; `assistant-ui/` lockfile committed; node_modules kept out of `src/` and the Python package)

## 6. Workbench integration

- [x] 6.1 Add conditional island include in `base.html` rendered only when the session has the `admin` scope; non-admin pages contain no assistant markup/scripts
- [x] 6.2 Verify bubble + panel do not obstruct existing pages (z-index/overflow spot-check on dashboard, clauses list, compare detail)

## 7. End-to-end verification

- [x] 7.1 E2E as admin: expand bubble, run a read (search clauses), a generation, and an evaluation through chat; replies stream in the panel
- [x] 7.2 E2E denial: anonymous and non-admin sessions get no entry point and are rejected at `/copilotkit/*`
- [x] 7.3 E2E destructive-tool exclusion: ask the assistant to delete a rubric/clause and confirm nothing is deleted and the tool is unavailable
- [x] 7.4 Failure drills: stop the runtime / MCP instance and confirm the panel shows an error and the rest of the site works
- [x] 7.5 Update `deploy/cheap-box/README.md` with the full topology (island → proxy → runtime → MCP instance) and rollback steps
