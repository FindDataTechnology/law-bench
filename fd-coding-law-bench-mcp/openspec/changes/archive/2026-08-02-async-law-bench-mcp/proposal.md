## Why

The law-bench MCP server (`fd-coding-law-bench-mcp`) currently wraps every tool as a synchronous function. FastMCP runs them on its async event loop via `anyio.to_thread`, so each tool call occupies a worker thread for the duration of the underlying work - psycopg blocking I/O, LLM-judge HTTP calls, LangGraph pipeline execution, Elasticsearch RAG queries. Under concurrent MCP clients (Claude Code running `pipeline_run`, `contract_evaluate`, `compare_run` in parallel, batch scripts fanning out across contract types), the thread pool saturates and tool latency compounds. The heaviest tools (`pipeline_run`, `contract_evaluate`, `compare_run`) each hold a thread through multi-second LLM round-trips and multi-iteration LangGraph loops, which is exactly the workload async I/O is designed to relieve. Converting the tool surface to native `async def` lets FastMCP await the work directly on the event loop, removes the per-call thread pinning, and unblocks concurrent tool calls without growing the thread pool.

## What Changes

- Convert every `@mcp.tool`-decorated function in `fd_coding_law_bench_mcp/tools/*.py` from `def` to `async def`, awaiting async variants of the wrapped calls.
- Introduce async wrappers around the sync `src.*` modules the tools call into (psycopg DB layer, LLM-judge scoring, LangGraph pipeline, RAG search, contract assembly), using `anyio.to_thread.run_sync` at the boundary for code that stays sync internally - keeping the thread hop at the outermost edge rather than inside every DB function.
- Replace the per-call `psycopg.connect(...)` pattern in `src/eval/db.py` with an async-aware connection strategy (async connection pool or a cached `AsyncConnection`), so DB-bound tools do not open and tear down a TCP connection per invocation.
- Update the test suite (`tests/test_*.py`) to drive the tools via FastMCP's async test client (`mcp.read_tool` / `mcp.call_tool` under `anyio`), replacing the current sync `mcp.call_tool(...)` usage.
- Update `server.py` / `__main__.py` if needed (FastMCP's `mcp.run()` already supports async tools; no change expected beyond verifying stdio transport still starts).

## Capabilities

### New Capabilities
- `async-tool-surface`: convert every MCP tool to `async def` and route sync `src.*` calls through `anyio.to_thread.run_sync` at the tool boundary.
- `async-db-connections`: replace per-call `psycopg.connect` with a reusable async connection (pool or cached `AsyncConnection`) so DB-bound tools share connections across calls.

### Modified Capabilities
<!-- No existing openspec specs to modify; this is the first change in the repo. -->

## Impact

- **Code**: all 10 tool modules under `fd_coding_law_bench_mcp/tools/` (clauses, compare, evaluate, generate, law_info, pipeline, prompts, rag, rubrics, tags) and the `src/eval/db.py` connection layer.
- **Tests**: every file under `fd_coding-law-bench-mcp/tests/` that calls tools sync today needs an async harness (`anyio` / `pytest-anyio` or FastMCP's async client).
- **Dependencies**: `anyio` is already pulled in transitively by FastMCP; `psycopg` (sync) is already a runtime dep. Adding `psycopg[asyncio]` (or using `AsyncConnection` from `psycopg`) is the only potential new dep - both are provided by the existing `psycopg` install, so no `pyproject.toml` change is expected.
- **API / client contract**: the MCP wire protocol is unchanged - tools still expose the same names and JSON schemas to clients. Only the server-internal implementation flips to async. No breaking change for MCP clients.
- **Runtime**: the stdio server entry point (`mcp.run()`) is unchanged; FastMCP natively schedules `async def` tools on its event loop.
