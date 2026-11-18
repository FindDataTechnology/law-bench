# law-bench-mcp — Delta

## ADDED Requirements

### Requirement: Streamable HTTP Transport
The MCP server SHALL support a streamable-HTTP transport selected by the
`MCP_HTTP_TRANSPORT` environment variable. When the variable is unset or `stdio`, the
server SHALL behave exactly as specified elsewhere in this capability (stdio, no token
required). When it is `http`, the server SHALL serve the same advertised tool set over
streamable HTTP, bound to `MCP_HTTP_HOST` (default `0.0.0.0`) and `MCP_HTTP_PORT`
(default `8080`). When serving HTTP, the server SHALL require a shared access token via
`MCP_HTTP_TOKEN`: if that variable is unset or empty the server SHALL refuse to start
(fail-closed), and any HTTP request that does not present the configured token SHALL be
rejected before any tool executes. The stdio path SHALL NOT require a token. Adding the
HTTP transport SHALL NOT change any tool's name, signature, or behavior.

#### Scenario: Default invocation is unchanged
- **WHEN** the server is launched with `python -m fd_coding_law_bench_mcp` and no
  `MCP_HTTP_TRANSPORT` variable
- **THEN** it runs over stdio exactly as before this requirement existed, with no token
  requirement

#### Scenario: HTTP transport serves the same tool set
- **WHEN** the server is launched with `MCP_HTTP_TRANSPORT=http` and a configured
  `MCP_HTTP_TOKEN`
- **THEN** the tool set advertised over streamable HTTP equals the stdio tool set, and
  an authenticated client can invoke each tool with the same arguments and results

#### Scenario: HTTP without a configured token refuses to start
- **WHEN** the server is launched with `MCP_HTTP_TRANSPORT=http` and no
  `MCP_HTTP_TOKEN`
- **THEN** the server exits with an error before binding any port

#### Scenario: Unauthenticated HTTP requests are rejected
- **WHEN** an HTTP request arrives without the token (or with a wrong token)
- **THEN** it is rejected before any tool dispatch, and no tool executes
