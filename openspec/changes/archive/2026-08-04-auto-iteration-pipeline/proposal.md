## Why

现有 pipeline (`pipeline_run`) 的 self-heal 循环只记录 `clause_review` recommendations 但从不执行，导致坏条款反复污染装配、分数无法持续提升。需要一条能**自动应用**高置信度改进的新 pipeline，形成持续学习闭环，同时保留现有手动 pipeline 不变。

## What Changes

- **New Capability**: `auto-iteration-pipeline` - 在标准 pipeline 的 store 之后追加 `learn` 节点，自动 reject 累计达阈值的 custom clauses
- **New MCP tool**: `auto_pipeline_run` - 暴露自动迭代 pipeline 给外部调用
- **Schema migration**: `pipeline_runs` 新增 `learn_applied` JSONB 列记录每次自动应用的操作
- **No breaking changes**: 现有 `pipeline_run` 完全不受影响，新 pipeline 独立运行

## Capabilities

### New Capabilities
- `auto-iteration-pipeline`: extends the standard contract pipeline with a learn node that auto-applies high-confidence clause rejections based on accumulated recommendations from current and historical runs

### Modified Capabilities
- `contract-pipeline`: adds `learn_applied` column to pipeline_runs schema (additive, non-breaking)

## Impact

- **New files**: `pipeline/learn.py`, `pipeline/auto_graph.py`, `tools/auto_pipeline.py`
- **Modified files**: `server.py` (register new tool), `pipeline/graph.py` (PipelineState.learn_applied field), `src/eval/store.py` (additive column migration)
- **DB migration**: `ALTER TABLE pipeline_runs ADD COLUMN learn_applied JSONB` (idempotent, auto-run via ensure_schema)
- **Safety**: only rejects custom clauses (base/tagged never touched); threshold configurable via `AUTO_REJECT_THRESHOLD` env var (default 3)
