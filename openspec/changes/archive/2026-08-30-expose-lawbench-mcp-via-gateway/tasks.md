# Tasks: expose-lawbench-mcp-via-gateway

## 1. MCP HTTP transport (`fd-coding-law-bench-mcp`)

- [x] 1.1 Add transport selection in `server.py`/`__main__.py`: `MCP_HTTP_TRANSPORT`
  env (`stdio` default → current behavior unchanged; `http` → FastMCP streamable HTTP on
  `MCP_HTTP_HOST`/`MCP_HTTP_PORT`)
- [x] 1.2 Fail-closed token guard: `MCP_HTTP_TRANSPORT=http` without a non-empty
  `MCP_HTTP_TOKEN` exits with an error before binding; HTTP requests lacking the token
  are rejected before tool dispatch
- [x] 1.3 Hermetic tests: HTTP tool set equals the stdio registration set; no-token boot
  refusal; unauthenticated request rejected; authenticated round-trip of one tool with
  `src.*` monkeypatched; stdio default unchanged

## 2. Image and k8s deployment (america box)

- [x] 2.1 Extend the law-bench image build to install `fd-coding-law-bench-mcp` into
  `/app/.venv`; verify inside the image: `python -c "import fd_coding_law_bench_mcp"`,
  origin entrypoint behavior unchanged (`PUBLIC_API` unset vs `=1` dry checks)
- [x] 2.2 Push the image to Harbor; create the MCP deployment in ns `law-bench`
  (command override, `MCP_HTTP_TRANSPORT=http`, `MCP_HTTP_TOKEN` in a k8s secret, same
  DB/LLM/MinIO config as origin) + ClusterIP→NodePort service on **30840**; confirm
  30840 unused by any service first
- [x] 2.3 Verify from the box: token-authenticated MCP session against
  `http://23.144.68.246:30840/mcp` lists the 52 tools; an unauthenticated request is
  rejected; the origin web pod (`lawbench.token118.com`) is unaffected

## 3. Gateway registration

- [x] 3.1 Write `scripts/infra/register_mcp_gateway.py` (mint Logto M2M token via
  `mcpgatewaym2m` + resource `https://mcp.token118.com/api`, then
  `POST /api/servers/register` with `deployment=remote`, `transport=streamable-http`,
  `proxy_pass_url=http://23.144.68.246:30840/mcp`, `auth_scheme=api_key`,
  non-public visibility, `overwrite=true`)
- [x] 3.2 Check the mcpgw proxy timeout for long tool calls; raise it for this backend
  if configurable, else note the constraint in the runbook
- [x] 3.3 Run the registration; verify: entry in `GET /api/servers` (M2M token), a
  gateway-authenticated MCP client connects through `mcp.token118.com` and calls one
  read tool successfully, an unauthenticated gateway call is rejected, and the entry is
  absent from the anonymous public ARD manifest

## 4. Runbook and cleanup

- [x] 4.1 Write `deploy/america-box/mcp-gateway-registration.md`: token mint, full
  registration parameter set, update/overwrite, removal (`POST /api/servers/remove`),
  rotation of `MCP_HTTP_TOKEN` (k8s secret + registry credential in one sequence),
  rollback (remove row + delete deployment/service)
- [x] 4.2 Cross-link from `deploy/america-box/mcp-gateway-logto-auth.md` follow-ups and
  from `fd-coding-law-bench-mcp/README.md` (HTTP mode section)
