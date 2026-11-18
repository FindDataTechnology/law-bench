## ADDED Requirements

### Requirement: DB-bound tools reuse a process-wide connection
Tools that call into `src/eval/db.py`-backed `src.*` functions SHALL NOT open a fresh `psycopg.connect(...)` per invocation. The connection layer SHALL provide a cached, process-wide connection (or connection wrapper) that is reused across tool calls within the MCP server process.

#### Scenario: Repeated tool calls reuse the same connection
- **WHEN** a tool like `clause_list` is invoked ten times in succession
- **THEN** the underlying psycopg connection is opened at most once (on first use) and reused for the subsequent nine calls; no new TCP connections are established per call.

#### Scenario: First-use lazy open
- **WHEN** the MCP server starts but no tool has been called yet
- **THEN** no psycopg connection has been opened; the connection is established lazily on the first tool invocation that needs it.

### Requirement: Connection strategy does not break non-MCP callers
The `src/eval/db.py` connection helper SHALL continue to support its existing sync callers (CLI, web app, batch scripts). The MCP-specific caching behavior SHALL be opt-in or scoped so that non-MCP callers observe the same per-call connection semantics they have today.

#### Scenario: Non-MCP caller uses `connect()`
- **WHEN** a non-MCP caller (e.g. a batch script) invokes `connect()` from `src/eval/db.py`
- **THEN** it receives a psycopg connection with the same lifetime and semantics as before the change (per-call open, caller-managed close).

#### Scenario: MCP tool uses the cached connection
- **WHEN** an MCP tool invokes its wrapped `src.*` function
- **THEN** the wrapped function, through the connection helper, reuses the cached process-wide connection rather than opening a new one.

### Requirement: Connection failure surfaces as a tool error
If the cached connection becomes invalid (e.g. DB restarts, network drop), the next tool invocation SHALL raise a tool error rather than silently returning stale data or hanging. The MCP server process SHALL remain running; a subsequent tool call after the error SHALL attempt to reconnect (or the operator SHALL restart the server).

#### Scenario: DB restart during server lifetime
- **WHEN** the PostgreSQL backend restarts while the MCP server is running
- **THEN** the next tool call that uses the cached connection raises a tool error with a message identifying the connection failure; the server process does not exit.
