# Proposal: expose-lawbench-mcp-via-gateway

## Why

The AI Gateway & Registry at `mcp.token118.com` (agentic-community/mcp-gateway-registry,
america box) is now live with Logto auth (see `swap-mcp-registry-idp-to-logto`) but its
catalog is empty. `fd-coding-law-bench-mcp` is the first real MCP server to register — yet
it can only run over **stdio** (`mcp.run()` in `server.py`), which means it can only ever
start on a developer's own machine with the repo + venv + `.env` present. No external AI
client can use law-bench's tools through the gateway. Adding an HTTP transport plus a
gateway registration makes the 52 contract-generation/evaluation/search tools reachable
from any MCP client via the gateway's single auth surface (Logto), with catalog
visibility, health checks, and centralized access control.

## What Changes

- Add a streamable-HTTP transport to the MCP server: `MCP_HTTP_TRANSPORT=http` (env-gated;
  stdio remains the default and all local workflows are unchanged). When serving HTTP the
  server requires a shared access token (`MCP_HTTP_TOKEN`) and refuses to bind without one
  (fail-closed, mirroring the public pod's `check_public_auth_config`).
- Deploy the MCP HTTP server as its own pod in the `law-bench` k8s namespace: same
  `harbor.local/law-bench/law-template` image (extended to install
  `fd-coding-law-bench-mcp` into the image venv), container command overridden to run the
  MCP server — `docker-entrypoint.sh` stays untouched. Exposed via NodePort **30840**
  (verified unused; origin web is 30820).
- Register the server in the gateway registry via its management API
  (`POST /api/servers/register`, Logto M2M token): `deployment=remote`,
  `transport=streamable-http`, `proxy_pass_url=http://23.144.68.246:30840/mcp`,
  `auth_scheme=api_key` (gateway forwards the shared token as `X-API-Key`).
- First release posture: registered **non-public** (not in the public ARD catalog;
  reachable by gateway-admin-group users). Tool-level curation (virtual server with a
  read-only subset) and public visibility are explicit follow-ups — this change registers
  the full 52-tool server for admin use only.
- Document the registration/rotation runbook in `deploy/america-box/`.

Out of scope: repointing law-bench/NewAPI Logto endpoints to `auth.token118.com`
(existing follow-up); public catalog visibility; tool-subset virtual servers; upstreaming
the Logto provider patch.

## Capabilities

### New Capabilities
- `lawbench-mcp-gateway`: how the law-bench MCP server is exposed through the AI Gateway
  & Registry — the k8s HTTP deployment shape (image/NodePort/token), the gateway
  registration parameters (remote, streamable-http, api_key scheme), the
  non-public-first visibility posture, and the registration/rotation runbook.

### Modified Capabilities
- `law-bench-mcp`: adds a streamable-HTTP transport requirement (env-gated, stdio default
  unchanged, fail-closed token requirement when serving HTTP). All existing tool
  requirements are untouched.

## Impact

- **Code**: `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/` (transport selection +
  token guard, likely in `server.py`/`__main__.py`); image build (install the MCP package
  into the venv).
- **Deploy**: new k8s manifest in `deploy/` (deployment + NodePort 30840 service in the
  `law-bench` namespace); america box registry registration (one-time API call +
  runbook).
- **Systems**: america box — one new pod (~LLM/DB/MinIO-configured like origin), one
  gateway catalog entry. Registry Mongo untouched beyond the new server row.
- **Risk surface**: through-gateway callers gain admin-grade tools (clause/rubric/prompt
  writes, LLM-budget-heavy pipelines) — acceptable while visibility is admin-only;
  mitigated in the follow-up public change by curating a read-only subset.
- **Rollback**: delete the k8s deployment/service and remove the registry server row
  (`POST /api/servers/remove`); stdio workflows never depended on any of this.
