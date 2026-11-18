# lawbench-mcp-gateway Specification

## Purpose
How the law-bench MCP server is exposed through the AI Gateway & Registry at
`mcp.token118.com`: the k8s deployment that serves the MCP streamable-HTTP endpoint, the
gateway registry registration that fronts it, and the operations to (re-)register or
remove it.

## Requirements

### Requirement: MCP HTTP Deployment
The MCP HTTP server SHALL run in the `law-bench` k8s namespace as its own deployment,
built from the same law-bench image — the image SHALL include the
`fd-coding-law-bench-mcp` package in its Python environment — with the container command
overridden to launch the HTTP transport. The shared `docker-entrypoint.sh` SHALL NOT be
modified to select MCP mode: the origin (`create_app()`) and public-pod (`PUBLIC_API=1`)
behaviors SHALL remain byte-for-byte unchanged. The deployment SHALL carry the same
DB / LLM / MinIO configuration as the origin pod, plus `MCP_HTTP_TRANSPORT=http` and the
`MCP_HTTP_TOKEN` value, and SHALL be exposed on NodePort `30840` (unused by any other
service on the box) so the MCP endpoint is reachable at `<box>:30840/mcp`.

#### Scenario: MCP endpoint reachable through the NodePort
- **WHEN** the MCP deployment is healthy and a client on the box opens a streamable-HTTP
  MCP session against `http://23.144.68.246:30840/mcp` presenting the configured token
- **THEN** the session succeeds and the advertised tool set matches the server's tool
  set

#### Scenario: Origin and public-pod behavior unchanged
- **WHEN** the image is rebuilt with the MCP package included and the origin pod (and, if
  deployed, the public pod) restart with their existing manifests
- **THEN** they serve the same web apps as before — no MCP-specific behavior is selected
  by the shared entrypoint

### Requirement: Gateway Registration
The MCP server SHALL be registered in the AI Gateway & Registry with
`deployment=remote`, `transport=streamable-http`, `proxy_pass_url` pointing at
`http://23.144.68.246:30840/mcp`, and `auth_scheme=api_key` with the shared token as the
gateway-held credential that the gateway forwards on proxied calls. Registration SHALL be
performed through the registry management API authenticated with a Logto M2M token
(`mcpgatewaym2m`, resource `https://mcp.token118.com/api`). The registered server SHALL
be non-public — excluded from the public ARD catalog — and SHALL be usable only by
gateway users in the admin group; making it public, or curating a public tool subset, is
a follow-up change.

#### Scenario: Registered server appears in the catalog
- **WHEN** the registration call completes and `GET /api/servers` is called with an M2M
  token
- **THEN** the law-bench entry is listed with its path, description, and remote/streamable-http
  deployment shape

#### Scenario: Gateway-authenticated tool call succeeds
- **WHEN** a gateway user in the admin group connects an MCP client through
  `mcp.token118.com` to the law-bench entry and invokes a read tool
- **THEN** the call is proxied to the NodePort endpoint with the gateway-held credential
  and returns the tool result

#### Scenario: Non-public entry stays out of the public catalog
- **WHEN** the public ARD manifest (`/.well-known/` catalog surface) is fetched
  anonymously
- **THEN** the law-bench server does not appear in it

### Requirement: Registration Runbook
The registration, credential rotation, and removal procedure SHALL be documented in
`deploy/america-box/` — including the M2M token mint, the full registration parameter
set, the removal call (`POST /api/servers/remove`), and the rollback note that deleting
the k8s deployment/service plus the registry row fully reverts the change — so the
procedure is reproducible without session history.

#### Scenario: Runbook enables reproduction and rollback
- **WHEN** an operator follows the runbook on a fresh session
- **THEN** they can mint an M2M token, re-register (or update) the server, verify it
  through the gateway, and remove it, using only documented commands
