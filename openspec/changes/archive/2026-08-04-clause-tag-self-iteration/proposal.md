## Why

当前 pipeline self-heal 只对**单次运行**排除有问题的 custom clauses，但不持久化修改。导致：1）重复劳动 - 每次重新 run 都要重新诊断；2）quality ceiling - bad clauses 持续污染 assembly；3）manual effort - 需要人工 review recommendations 并用 `clause_review`手动执行。系统收集了大量诊断数据（`actions_taken`, `recommendations`），但没有自动利用。

## What Changes

- **New Capability**: `clause-iteration-analyzer` - 分析 pipeline_runs 提取 clause/tag 修改建议
- **New Capability**: `auto-executor` - 基于分析结果自动执行 `clause_review` / `clause_update`
- **Threshold-based automation**: high-confidence recommendations auto-applied, medium/low for human review
- **Rollback support**: operation logging for safety

## Capabilities

### New Capabilities
- `clause-iteration-analyzer`: analyze pipeline_runs to identify clauses frequently excluded or recommended for rejection
- `auto-executor`: apply clause_review and clause_update operations based on analysis with dry-run and rollback support

### Modified Capabilities
- `contract-pipeline`: enhance improve node to persist learnings for analyzer consumption (minor enhancement)

## Impact

- **Affected components**: `pipeline_runs` table, `clauses` table (tag_review), existing MCP tools (`clause_review`, `clause_update`)
- **New scripts**: `scripts/analyze_clause_iteration.py`, `scripts/auto_clause_iteration.py`
- **No breaking changes**: operates as offline tool, does not modify existing pipeline graph structure
