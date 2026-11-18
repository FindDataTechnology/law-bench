## Why

The current MCP tools for contract generation are synchronous wrappers around thread-pooled functions, which limits concurrency and real-time API consumption. There's no way to enumerate all valid tag combinations or generate multiple contracts in parallel. Users cannot query contract content programmatically without triggering file I/O. This change enables async-native contract generation at scale.

## What Changes

- **New MCP Tools**:
  - `tag_combinations_list`: Enumerate all valid tag combinations for a contract type with clause availability metadata
  - `contract_generate_batch`: Generate multiple contracts in parallel across different tag combinations (explicit list or auto-enumerate)
  - `contract_content`: Return contract body as markdown/JSON directly without file I/O
  - `contract_type_catalog`: List all contract types with their slot counts, scenario vocabularies, and tagged clause coverage
  
- **Async Native Implementation**: 
  - Replace `anyio.to_thread.run_sync` wrappers with true async tool functions
  - Async DB access layer (asyncpg) for non-blocking reads
  - Parallel LLM calls via asyncio.gather for fill/cache operations
  
- **Breaking Changes**: None (backward compatible - sync tools remain functional)

## Capabilities

### New Capabilities

- `async-contract-generation`: True async implementation of contract generation APIs with batch support
- `tag-combinatorics`: Tag enumeration and combination analysis for exhaustive contract discovery
- `content-first-api`: Direct contract content returns (markdown/JSON) independent of file-based outputs

### Modified Capabilities

None. The existing sync tools remain functional as fallbacks; this is additive.

## Impact

**Affected Code**:
- `/fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/tools/*.py` - new tool files + async rewrites
- `/fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/server.py` - import new tools
- `/src/clauses/assemble.py` - add content-only return path (no file I/O)
- `/src/contracts/templates.py` - add catalog endpoint

**Dependencies**:
- Add `asyncpg` for async PostgreSQL access
- Add `httpx` for async HTTP if LLM client needs updating

**API Surface**:
- Current sync tools: retained for backward compatibility
- New async tools: added under same MCP server namespace
- No breaking changes to callers

**Systems**:
- PostgreSQL connection pool upgraded to async model (optional, best-effort fallback to sync)
- File I/O remains sync (docx/pdf rendering has no async equivalent)
