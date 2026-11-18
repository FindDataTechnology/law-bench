# Implementation Tasks

## Task 1: Create learn node
**Status**: ✅ Done
**File**: `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/pipeline/learn.py`

- [x] `learn_node()` function - aggregates current + historical rejections
- [x] `_aggregate_historical_rejections()` - cross-run aggregation
- [x] `_is_custom_clause()` - safety check (only reject custom)
- [x] `_update_learn_applied()` - persist results to pipeline_runs
- [x] `AUTO_REJECT_THRESHOLD` env var config (default 3)
- [x] Fail-safe exception handling

## Task 2: Create auto graph
**Status**: ✅ Done
**File**: `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/pipeline/auto_graph.py`

- [x] `build_auto_graph()` - reuses all nodes + learn node
- [x] `run_auto_pipeline()` - entry point with same signature as run_pipeline
- [x] `store -> learn -> END` edge added

## Task 3: Create MCP tool
**Status**: ✅ Done
**File**: `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/tools/auto_pipeline.py`

- [x] `auto_pipeline_run` tool registered
- [x] Same params as `pipeline_run`
- [x] Returns `learn_applied` field
- [x] Registered in `server.py`

## Task 4: Schema migration
**Status**: ✅ Done
**File**: `src/eval/store.py`

- [x] Add `learn_applied` JSONB column to `_ADDITIVE_COLUMNS`
- [x] Idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
- [x] Verified column exists in DB

## Task 5: PipelineState extension
**Status**: ✅ Done
**File**: `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/pipeline/graph.py`

- [x] Add `learn_applied: list` field to PipelineState TypedDict

## Task 6: Smoke tests
**Status**: ✅ Done

- [x] Verify all imports work
- [x] Verify auto_pipeline_run tool registered (45 tools total)
- [x] Verify schema migration (learn_applied column exists)
- [x] Verify historical aggregation works (employment: 7263->2, 7264->1, etc.)
- [x] Verify learn_node logic (7263: 2+2=4 >= 3 -> rejected)
- [x] Verify rejection applied (7263 tag_review all 'rejected')

## Task 7: End-to-end test
**Status**: ✅ Done

- [x] Run `auto_pipeline_run(contract_type="employment", stance="balanced")` -> pipeline_run_id=352
- [x] Verify learn_applied in returned result -> [{clause_id:7266, total_count:3, current_count:1, historical_count:2}]
- [x] Verify pipeline_runs row has learn_applied populated -> DB row 352 confirmed
- [x] Run standard `pipeline_run` to confirm it's unaffected -> pipeline_run_id=353, no learn_applied field

## Acceptance Criteria
1. ✅ `auto_pipeline_run` executes learn node after store
2. ✅ Custom clauses at threshold are auto-rejected
3. ✅ Base/tagged clauses never touched
4. ✅ learn_applied persisted to DB and returned in result
5. ✅ Standard pipeline_run unchanged
6. ✅ Fail-safe: learn node never crashes pipeline
