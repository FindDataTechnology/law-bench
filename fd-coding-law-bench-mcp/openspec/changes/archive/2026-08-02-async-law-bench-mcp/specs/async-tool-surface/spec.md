## ADDED Requirements

### Requirement: Every MCP tool is an async function
The system SHALL define every `@mcp.tool`-decorated function in `fd_coding_law_bench_mcp/tools/*.py` as `async def`. No tool SHALL remain a synchronous `def`.

#### Scenario: Tool registration after conversion
- **WHEN** the MCP server starts and registers tools
- **THEN** every tool exposed over the MCP wire is backed by an `async def` implementation, and FastMCP dispatches it directly on the event loop without wrapping it in `anyio.to_thread` implicitly.

### Requirement: Sync `src.*` calls are wrapped at the tool edge
Each tool SHALL invoke the underlying sync `src.*` function(s) via a single `await anyio.to_thread.run_sync(...)` call at the outermost edge of the tool body. Tools that call multiple `src.*` functions in sequence (e.g. read-then-transform) SHALL wrap the whole sequence in one `run_sync` hop, not one per call.

#### Scenario: Tool with multiple internal sync calls
- **WHEN** a tool like `pipeline_get` reads a pipeline row and then a linked eval row
- **THEN** the tool body performs both reads inside a single `run_sync` invocation, incurring exactly one thread-hop for the tool call.

#### Scenario: Tool with a single sync call
- **WHEN** a tool like `clause_list` calls one `src.*` function
- **THEN** the tool body is `async def` and does `return await anyio.to_thread.run_sync(list_clauses, ...)`.

### Requirement: MCP wire contract is unchanged
The conversion SHALL NOT alter tool names, parameter schemas, or return shapes as observed by MCP clients. The JSON schema advertised for each tool before and after the change SHALL be identical.

#### Scenario: Client observes no breaking change
- **WHEN** an MCP client (e.g. Claude Code) lists tools on the server after the conversion
- **THEN** the tool names, parameter names/types, and return value shapes match those observed before the conversion.

### Requirement: Tests drive tools via an async harness
The test suite SHALL invoke tools through an async test client (FastMCP's async `call_tool` or equivalent under `anyio`). No test SHALL wrap an async tool call in a per-call `asyncio.run(...)`.

#### Scenario: Running the test suite
- **WHEN** `pytest` runs the tool tests
- **THEN** each test is an `async def` (or marked for anyio) and awaits the tool call directly; the suite passes with the same assertions as before the conversion.
