# Proposal: Pipeline Rename and Tag Iteration

## Why

当前 pipeline 命名不清晰（`pipeline_run`、`auto_pipeline_run`），难以区分用途。同时需要新增 `tag_iteration` pipeline，自动分析并修改 clause tags，通过 re-evaluate 验证效果。

## What Changes

### 1. Pipeline 重命名

| 当前名称 | 新名称 | 说明 |
|---------|--------|------|
| `pipeline_run` | `self_heal_pipeline_run` | 标准自愈流程，只读 clauses |
| `auto_pipeline_run` | `auto_reject_pipeline_run` | 自动 reject 差条款，幂等写 tag_review |

### 2. 新增 tag_iteration pipeline

分两步：
- `tag_iteration_suggest`: 分析失败 clauses，LLM 建议新 tags（只读）
- `tag_iteration_apply`: 应用审批后的 tag 修改，re-evaluate 验证，分数下降则 rollback

### 3. 并发安全

- `self_heal_pipeline_run`: ✅ 可并发（只读）
- `auto_reject_pipeline_run`: ✅ 可并发（learn_node 幂等）
- `tag_iteration_suggest`: ✅ 可并发（只读）
- `tag_iteration_apply`: ❌ 必须串行（用 `pg_advisory_lock` 保护）

## Capabilities

### New Capabilities

- `tag-iteration-pipeline`: 自动分析并修改 clause tags，re-evaluate 验证效果，支持 rollback

### Modified Capabilities

- `self-heal-pipeline`: 重命名 `pipeline_run` → `self_heal_pipeline_run`，加注释
- `auto-reject-pipeline`: 重命名 `auto_pipeline_run` → `auto_reject_pipeline_run`，加注释

## Impact

- **Affected files**:
  - `pipeline/graph.py` → 重命名为 `self_heal_graph.py`，加注释
  - `pipeline/auto_graph.py` → 重命名为 `auto_reject_graph.py`，加注释
  - `tools/pipeline.py` → 重命名为 `tools/self_heal_pipeline.py`，tool 改名
  - `tools/auto_pipeline.py` → 重命名为 `tools/auto_reject_pipeline.py`，tool 改名
  - `pipeline/tag_iteration_graph.py` (新增)
  - `pipeline/suggest_retag.py` (新增)
  - `tools/tag_iteration.py` (新增)
- **DB changes**: 无 schema 变更
- **Backward compatibility**: 旧 tool 名称保留为 alias（deprecated）
