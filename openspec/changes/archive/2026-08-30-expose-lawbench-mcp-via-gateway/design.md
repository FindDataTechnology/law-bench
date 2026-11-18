# Design: expose-lawbench-mcp-via-gateway

## Context

Two systems must connect, both already verified live:

1. **law-bench MCP** (`fd-coding-law-bench-mcp/`) — FastMCP 3.x, 52 tools across 18
   modules, stdio-only today (`mcp.run()` in `server.py:39`). Imports `src.*` in place;
   needs the shared venv plus `.env` (DB / RAG / LLM / MinIO config).
2. **AI Gateway & Registry** (`mcp.token118.com`, `/opt/mcp-gateway-registry` on the
   america box) — registry = catalog + management plane; `mcpgw-server` = MCP data plane
   that proxies tool calls to a backend endpoint. Registration model
   (`registry/core/schemas.py`): `deployment=remote` proxies to a live `proxy_pass_url`
   (`streamable-http`/`sse`); `deployment=local` only stores a launch recipe (registry
   runs nothing). Backends auth via `none`/`bearer`/`api_key` (`X-API-Key` default
   header). Catalog is empty; M2M management access works
   (`swap-mcp-registry-idp-to-logto` task 5.3).

Deployment context: the law-bench origin runs in k8s ns `law-bench` (NodePort 30820 =
web); the registry stack runs in Docker Compose on the same box and reaches other
services via host NodePorts (the pattern Caddy already uses for 30820).

## Goals / Non-Goals

**Goals**: law-bench's 52 tools reachable from any MCP client through
`mcp.token118.com` with Logto-backed access control; local stdio workflows untouched;
reproducible registration/rollback.

**Non-Goals**: public catalog visibility or tool-subset curation (follow-up); Logto
endpoint repoint (existing follow-up); the REST `api/` FastAPI app (separate surface,
untouched); multi-version routing.

## Decisions

### D1 — Decision delegated, chosen: remote deployment over a local recipe

The user delegated the mode decision. `deployment=local` (registry stores a launch
recipe) was rejected: it requires every user's machine to hold the repo, venv, and DB/LLM
credentials — it distributes the existing `mcp-config.example.json` with no gateway
value. `deployment=remote` makes the gateway meaningful (single auth surface, catalog,
health, access control) and matches law-bench's existing public-exposure posture.

### D2 — HTTP transport via FastMCP's streamable-HTTP support, env-gated

FastMCP 3.x natively serves streamable HTTP (`mcp.run(transport="http")` / `http_app()`),
so the transport addition is selection + guard logic in `server.py`/`__main__.py` — no
framework change. Env-gated (`MCP_HTTP_TRANSPORT`, default stdio) so every existing
invocation (`.mcp.json`, tests, `fastmcp run`) is untouched. The token guard: when HTTP
is selected without `MCP_HTTP_TOKEN`, exit before binding (fail-closed, mirroring the
public pod's `check_public_auth_config`); requests are checked against the configured
token before tool dispatch (FastMCP auth hook or a thin ASGI wrapper — implementation
choice, spec only demands the behavior).

- *Alternative: mount the MCP ASGI app inside the origin FastAPI app* — one fewer pod,
  but couples web redeploys to MCP availability and tangles the public-pod posture;
  rejected.
- *Alternative: run MCP in the existing public pod* — public pod is read-only/replica;
  MCP writes go to the origin primary. Rejected.

### D3 — Same image, separate pod, command override (entrypoint untouched)

Extend the image build to install `fd-coding-law-bench-mcp` into `/app/.venv` (one
pip/hatch step; the package already builds as a wheel wrapping `src.*` in place). The
new deployment overrides the container command to run
`python -m fd_coding_law_bench_mcp` with `MCP_HTTP_TRANSPORT=http` — `docker-entrypoint.sh`
stays byte-for-byte unchanged, so the harbor-seed + origin/public selection logic carries
zero regression risk. Config mirrors the origin secret set (origin **primary** DB — MCP
tools legitimately write rubrics/clauses, unlike the read-only public pod).

### D4 — NodePort 30840 + api_key scheme (not `none`)

NodePort 30840 is verified unused on the box. k3s NodePorts bind on all interfaces, so
the endpoint is nominally internet-reachable — the shared token (`auth_scheme=api_key`,
registry default header `X-API-Key`) is therefore mandatory, not optional defense: the
gateway holds the credential and forwards it on proxied calls; direct unauthenticated
hits are rejected by the MCP server itself. Bearer-vs-API-key: `api_key` matches the
registry default and the law-bench public API precedent (`X-API-Key`).

### D5 — Non-public registration first, curated public subset later

Auto tool discovery registers all 52 tools — including destructive ones (`clause_delete`,
`prompt_delete`, …) and LLM-budget-heavy pipelines. Until a curated public subset exists
(virtual server per the registry's tool-mapping feature, follow-up change), the
registration is non-public: absent from the anonymous ARD manifest, usable by
gateway-admin-group users only. This is the same least-privilege direction the Logto swap
used (absent claim → no admin).

### D6 — Registration as script + runbook, not tribal knowledge

A small `scripts/infra/` helper (mint Logto M2M token → `POST /api/servers/register`)
plus `deploy/america-box/mcp-gateway-registration.md` runbook (register / update /
remove / rotate). Removal is one API call + `kubectl delete` — full rollback in minutes.

## Risks / Trade-offs

- [mcpgw proxy timeout kills long tool calls] → pipeline/compare tools run minutes;
  check the mcpgw request timeout at implementation and raise it for this backend if
  configurable, else document the constraint (admin-only callers can run long tools
  locally via stdio in the meantime).
- [Registry image upgrade drift] → registration parameters live in the runbook, not the
  registry UI; re-registration is idempotent (`overwrite=true`).
- [NodePort reachability from the compose network] → mcpgw targets
  `23.144.68.246:30840` (host IP) the same way Caddy fronts 30820; verify from the
  mcpgw container before registering.
- [Token leakage via repo] → `MCP_HTTP_TOKEN` lives in the k8s secret and the registry
  credential store, never in git; the runbook references the secret, not the value.
- [Image grows by the MCP package] → the package is a thin wrapper + fastmcp/pydantic
  deps; acceptable.

## Migration Plan

1. Add transport + token guard to the MCP server; hermetic tests (HTTP set == stdio set,
   no-token boot refusal, unauthenticated request rejected).
2. Extend the image build; push to Harbor; deploy the MCP pod + NodePort 30840 service.
3. Verify direct: token-authenticated MCP session against `<box>:30840/mcp`; origin pod
   unaffected.
4. Register via the script (remote/streamable-http/api_key, non-public); verify catalog
   listing, gateway-authenticated tool call, anonymous ARD absence.
5. Write the runbook; record rollback (remove row + delete deployment).

## Open Questions

- mcpgw per-backend timeout configurability (checked at implementation; does not change
  the approach).
- Whether FastMCP's native auth hook or a thin ASGI guard implements the token check
  (behavior is specified; mechanism is free).
