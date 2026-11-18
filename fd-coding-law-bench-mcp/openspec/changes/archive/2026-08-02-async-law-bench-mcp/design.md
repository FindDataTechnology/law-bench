## Context

`fd-coding-law-bench-mcp` is a thin FastMCP wrapper over the law-bench `src.*` modules (eval, clauses, contracts, search, pipeline). Today every tool is a plain `def` that calls into sync `src.*` code - psycopg connections opened per call, LLM-judge HTTP requests, LangGraph pipeline loops, Elasticsearch RAG queries. FastMCP's stdio server runs an asyncio event loop; sync tools are dispatched onto a worker thread via `anyio.to_thread`, so each in-flight tool call pins one thread for its entire duration.

The heaviest tools - `pipeline_run` (LangGraph loop with multiple LLM calls + DB writes), `contract_evaluate` (LLM judge over N criteria), `compare_run` (N drafts x M criteria LLM judge calls) - hold a thread through multi-second or multi-tens-of-seconds LLM round-trips. When Claude Code (or a batch script) fires several of these concurrently, the default thread pool saturates and tool latency compounds linearly. The fix is to make the tools native `async def` so FastMCP can await them on the event loop, and to push the sync/async boundary out to the outermost edge of the wrapped code.

Constraints:
- The `src.*` modules are shared with the law-bench web app and CLI; their sync API must keep working for those callers.
- psycopg is used in its sync form throughout `src/eval/db.py`, `src/eval/store.py`, `src/clauses/store.py`, etc. Rewriting all of `src.*` to async is out of scope.
- The MCP wire protocol (tool names, JSON schemas, return shapes) must not change - this is a server-internal refactor.

## Goals / Non-Goals

**Goals:**
- Every `@mcp.tool` in `fd_coding_law_bench_mcp/tools/*.py` becomes `async def`.
- The sync/async boundary is pushed to the outermost edge: each tool wraps its `src.*` call(s) in a single `anyio.to_thread.run_sync(...)` hop, not one per DB query or LLM call inside the tool body.
- DB-bound tools stop opening a fresh `psycopg.connect(...)` per invocation; a process-wide connection (or small pool) is reused.
- Tests drive tools through FastMCP's async client; existing sync test helpers are replaced.
- MCP client contract (tool names, schemas, return shapes) is unchanged.

**Non-Goals:**
- Rewriting `src.*` itself to be async. The `src.*` modules stay sync; the MCP wrapper is the only async layer.
- Introducing a full connection pooler (e.g. `psycopg_pool.AsyncConnectionPool`) unless the simpler cached-connection approach proves insufficient. Start with a single cached `AsyncConnection` (or a sync connection used from a dedicated worker thread) and escalate only if contention shows up.
- Changing the stdio transport, adding HTTP/SSE transport, or modifying FastMCP version pin.
- Parallelizing inner work (e.g. scoring criteria concurrently inside `contract_evaluate`). That's a separate optimization; this change only removes the per-tool thread pin.

## Decisions

### 1. Async boundary placement: wrap at the tool edge, not inside `src.*`

**Decision**: each `async def` tool does `await anyio.to_thread.run_sync(sync_fn, *args)` once, around the outermost `src.*` call. The `src.*` modules stay fully sync.

**Rationale**: rewriting `src/eval/store.py`, `src/clauses/store.py`, `src/eval/scoring.py`, etc. to async would touch ~15 modules and break the non-MCP callers (CLI, web app, batch scripts). Pushing the boundary to the tool edge gives 95% of the benefit (the thread hop happens once per tool call, not per DB query) with 5% of the churn. FastMCP already dispatches sync tools this way; making it explicit in the tool code just removes the implicit per-call thread pin and lets multiple tools share the event loop while their inner sync work runs on the pool.

**Alternatives considered**:
- *Full async rewrite of `src.*`*: rejected - too large a surface, breaks non-MCP callers, no benefit over the outer-wrap approach for this workload.
- *Leave tools as `def` and just tune the thread pool*: rejected - FastMCP's default pool size is bounded; tuning it papers over the problem and doesn't help the LLM-bound tools that block for tens of seconds.

### 2. DB connection strategy: cached process-wide connection, opened lazily

**Decision**: introduce a small async-aware helper in `src/eval/db.py` that returns a process-wide connection (or connection wrapper) reused across calls. For the MCP server, the helper returns a sync `psycopg.Connection` held in a module-level slot and accessed from the worker thread inside `run_sync`; the tool's `async def` body awaits the `run_sync` call, so the event loop is free while the worker thread blocks on psycopg.

**Rationale**: the current `connect(db)` opens a fresh TCP connection to PostgreSQL on every tool call and closes it in `finally`. For a tool like `clause_list` that's fine; for `pipeline_run` that fans out to multiple `src.*` functions each opening their own connection, it's wasteful. A cached connection eliminates the per-call TCP + auth overhead. We keep it sync (not `AsyncConnection`) because the `src.*` callers are sync; the async benefit comes from the tool edge being `async def`, not from the DB driver being async.

**Alternatives considered**:
- *`psycopg.AsyncConnection` + rewrite `src.*` to `await conn.execute(...)`*: rejected - same surface-area problem as decision 1.
- *`psycopg_pool.AsyncConnectionPool`*: overkill for a single-process MCP server with modest concurrency; revisit only if connection contention shows up in practice.
- *One connection per tool call, but from a pool*: adds pool lifecycle complexity without measurable benefit at the expected tool-call rate.

### 3. Tool-by-tool conversion pattern

**Decision**: every tool follows the same shape:
```python
@mcp.tool(tags={...})
async def tool_name(...) -> ...:
    import anyio
    from src.some.module import sync_fn
    return await anyio.to_thread.run_sync(sync_fn, *args)
```
Tools that call multiple `src.*` functions in sequence (e.g. `pipeline_get` reads pipeline row then eval row) wrap the whole sequence in a single `run_sync` via a small local helper, not one `await` per call.

**Rationale**: consistency across 10 tool modules makes the change mechanical and reviewable. A single `run_sync` per tool call keeps the thread-hop overhead constant regardless of how many internal DB queries the tool triggers.

**Alternatives considered**:
- *Wrap each `src.*` call individually inside the tool*: rejected - N thread hops per tool call, defeats the purpose.
- *Introduce an `async` mirror of every `src.*` function*: rejected - duplicates the sync surface.

### 4. Test harness: `anyio` + FastMCP's async client

**Decision**: convert `tests/conftest.py` and every `test_*.py` to use `anyio` (via `pytest-anyio` or `pytest.mark.anyio`) and FastMCP's async tool-call API. The existing `mcp.call_tool(...)` sync helper is replaced with `await mcp.call_tool(...)` (or the equivalent async entry point exposed by the installed FastMCP version).

**Rationale**: the tools are now `async def`; sync test helpers would have to spin up their own event loop per call, which is exactly the pattern we're trying to eliminate in production. Using `anyio` in tests matches production behavior.

**Alternatives considered**:
- *Keep sync tests, wrap each call in `asyncio.run(...)`*: rejected - adds an event-loop-per-test overhead and masks real concurrency bugs.

## Risks / Trade-offs

- **[psycopg connection lifetime vs. server lifetime]** → Mitigation: the cached connection is opened lazily on first use and closed when the process exits. If the DB restarts, psycopg will raise on the next execute; the tool surfaces that as a tool error. A future improvement can add reconnect-on-failure; for now, restart the MCP server.
- **[Thread pool still used for sync work]** → Mitigation: the thread pool is still the execution substrate for `src.*` code, but each tool now holds one thread for one tool call (not one per internal query). If concurrent tool volume grows enough to saturate the pool, the next lever is `psycopg.AsyncConnection` + async `src.*` - explicitly deferred.
- **[Tests must all be converted in one pass]** → Mitigation: the change is mechanical (wrap each test body in `async def`, swap `mcp.call_tool` for `await mcp.call_tool`). Do all tool modules in one PR to avoid a mixed sync/async test matrix.
- **[FastMCP version compatibility]** → Mitigation: FastMCP has supported `async def` tools since early versions; the current pin (`>=3.2,<4`) is well past that. Verify with a single tool first.
- **[Cached connection not safe across fork / reload]** → Mitigation: the MCP server is a single-process stdio server; no forking. If the server is later run under a worker model, revisit.

## Migration Plan

1. Add `anyio` to the dev/test env if not already present (it's a transitive dep of FastMCP, so likely no `pyproject.toml` change).
2. Convert tools module-by-module in dependency order: read-only tools first (`law_info`, `tags`, `prompts`, `rubrics`, `clauses` read paths), then write tools (`clauses` write paths, `evaluate`, `generate`, `compare`, `pipeline`).
3. After each module, run its test file to confirm behavior is unchanged.
4. Convert the test harness (`conftest.py`) once, then update each `test_*.py` to match.
5. Smoke test end-to-end: invoke `pipeline_run`, `contract_evaluate`, `compare_run` concurrently from a small script and confirm latency does not compound linearly.
6. Rollback: revert the PR; no data model or wire-protocol changes to unwind.

## Open Questions

- None currently. The scope is narrow and the pattern is mechanical.
