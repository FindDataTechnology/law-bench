# law-bench-mcp — Delta Spec

## ADDED Requirements

### Requirement: Tool Denylist
The MCP server SHALL support excluding a configured set of tools from advertisement via environment configuration (`MCP_TOOL_DENYLIST`, comma-separated tool names). Excluded tools SHALL NOT appear in tool listings and SHALL NOT be invocable. When the setting is unset or empty, all tools SHALL be advertised (behavior unchanged for existing clients). The setting SHALL apply on both stdio and streamable HTTP transports.

#### Scenario: Denylisted tools are not advertised
- **WHEN** the server starts with `MCP_TOOL_DENYLIST=clause_delete,rubric_delete,criterion_delete,prompt_delete` and a client lists tools
- **THEN** the denylisted tools are absent from the listing and all other tools are present

#### Scenario: Denylisted tool is not invocable
- **WHEN** a client calls a denylisted tool by name
- **THEN** the call fails as an unknown tool and no data is changed

#### Scenario: Default keeps the full toolset
- **WHEN** the server starts without `MCP_TOOL_DENYLIST`
- **THEN** all tools are advertised exactly as before this change
