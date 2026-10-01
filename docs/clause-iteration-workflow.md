# Clause & Tag Self-Iteration Workflow

本文档描述如何使用自动化脚本从 pipeline 运行数据中学习并改进条款库。

## Overview

系统通过两个阶段实现条款自迭代：

1. **Analyzer** - 分析历史 pipeline 运行，识别问题条款
2. **Auto-executor** - 安全地应用改进建议（支持 dry-run）

## Quick Start

### 1. 运行分析器

```bash
# 分析最近 50 次 pipeline 运行
PYTHONPATH=<repo-root>:$PYTHONPATH \
  python scripts/analyze_clause_iteration.py \
    --limit 50 \
    --output analysis.json

# 输出示例：
# [1] 被排除的 Custom Clauses (出现次数: 0)
# [2] Recommendations 中的 Reject 建议 (共 12 条)
# [3] Score vs Exclusion Trend (样本数：50)
#   平均分：0.00
#   All-pass 率：0.0%
# [4] 推荐操作列表
#   #1 [confidence:medium] id=7257 section=所有权保留
#       reject_count: 4, reasons: [...]
```

### 2. 审查建议

```bash
# 查看高置信度推荐
cat analysis.json | python -m json.tool | \
  jq '.[] | select(.confidence=="high")'

# 查看所有推荐
cat analysis.json | python -m json.tool
```

### 3. Dry-run 验证

```bash
# 预览将要执行的操作（不修改数据库）
PYTHONPATH=<repo-root>:$PYTHONPATH \
  python scripts/auto_clause_iteration.py \
    --analysis analysis.json \
    --confidence high \
    -n

# 输出示例：
# Loaded 3 recommendations
#   [REJECT] id=7257 [DRY RUN]
#   [REJECT] id=7263 [DRY RUN]
# Results Summary:
#   Total: 3, Success: 3, Skipped: 0
```

### 4. 应用更改

```bash
# 实际应用更改（记录操作日志）
PYTHONPATH=<repo-root>:$PYTHONPATH \
  python scripts/auto_clause_iteration.py \
    --analysis analysis.json \
    --confidence high \
    --commit-log ops_log.jsonl

# 验证更改已应用
# 通过 MCP 工具查询条款状态
```

## Analyzer 详解

### 功能

- **统计排除频率**: 哪些 custom clauses 在 self-heal 中被频繁排除
- **聚合 LLM 建议**: 汇总 improve 节点的 reject recommendations
- **计算置信度**: 基于排除次数和拒绝次数分配 high/medium/low
- **输出 JSON**: 生成可执行的推荐列表

### 置信度阈值

| Confidence | Exclude Count | Reject Count | 建议操作 |
|------------|--------------|--------------|----------|
| **high**   | ≥5           | ≥5           | 自动应用 |
| **medium** | 3-4          | 2-4          | 人工审查 |
| **low**    | <3           | <2           | 忽略 |

### CLI 参数

```bash
--limit N              # 分析最近 N 次运行（默认 50）
--threshold-exclude N  # 排除次数阈值（默认 3）
--threshold-reject N   # 拒绝次数阈值（默认 2）
--output FILE          # 输出 JSON 文件路径
```

## Auto-executor 详解

### 安全机制

1. **Dry-run 模式** (`-n`): 预览不执行
2. **置信度过滤**: 只应用高置信度建议
3. **操作日志**: 记录所有更改到 JSONL
4. **Assembly-ready 检查**: 跳过 tag_review 不完整的条款

### CLI 参数

```bash
--analysis FILE        # 分析结果 JSON 文件
--confidence LEVEL     # 最低置信度阈值（high/medium/low）
-n, --dry-run          # 预览模式
--commit-log FILE      # 操作日志路径
```

### 操作类型

当前支持：
- **reject_clauses**: 调用 `clause_review(id, 'rejected')` 标记条款为 rejected

未来扩展：
- **update_body**: 修改条款内容
- **update_tags**: 修改条款标签

## Workflow 示例

### 场景 1: 首次运行

```bash
# 1. 积累数据（先运行 50+ 次 pipeline）
for i in {1..50}; do
  python -c "from src.eval.pipeline_store import pipeline_run; pipeline_run('sale', stance='balanced')"
done

# 2. 分析
python scripts/analyze_clause_iteration.py --limit 50 --output analysis.json

# 3. 审查
cat analysis.json | python -m json.tool | less

# 4. Dry-run
python scripts/auto_clause_iteration.py --analysis analysis.json --confidence high -n

# 5. 应用
python scripts/auto_clause_iteration.py --analysis analysis.json --confidence high --commit-log ops.jsonl
```

### 场景 2: 持续改进

```bash
# 每周运行一次
python scripts/analyze_clause_iteration.py --limit 100 --output weekly.json
python scripts/auto_clause_iteration.py --analysis weekly.json --confidence high --commit-log weekly_ops.jsonl

# 查看操作历史
cat weekly_ops.jsonl | python -m json.tool
```

## Troubleshooting

### 问题 1: ModuleNotFoundError

**症状**: `ModuleNotFoundError: No module named 'src'`

**解决**: 设置 PYTHONPATH
```bash
export PYTHONPATH=<repo-root>:$PYTHONPATH
```

### 问题 2: 没有推荐

**症状**: 分析器输出空推荐列表

**原因**:
- Pipeline 运行次数太少（需要 50+ 次）
- 阈值设置太高

**解决**:
```bash
# 降低阈值
python scripts/analyze_clause_iteration.py \
  --limit 100 \
  --threshold-exclude 2 \
  --threshold-reject 1 \
  --output analysis.json
```

### 问题 3: Dry-run 全部跳过

**症状**: `Skipped: 3, Success: 0`

**原因**: 推荐置信度低于阈值

**解决**:
```bash
# 使用更低的置信度阈值
python scripts/auto_clause_iteration.py \
  --analysis analysis.json \
  --confidence medium \
  -n
```

### 问题 4: 应用后没有效果

**症状**: 执行了 reject 但 pipeline 分数没有提升

**原因**:
- 被 reject 的条款可能不是主要问题
- 需要更多数据积累

**解决**:
- 检查 `analysis.json` 中的 reasons 字段
- 手动审查被 reject 的条款是否真的有问题
- 考虑调整阈值或增加样本量

## Best Practices

1. **先 dry-run**: 总是先用 `-n` 预览
2. **高置信度优先**: 只自动应用 high confidence
3. **人工审查 medium**: medium confidence 需要人工确认
4. **记录操作**: 使用 `--commit-log` 跟踪更改
5. **渐进式应用**: 不要一次应用太多更改
6. **验证效果**: 应用后重新运行 pipeline 测量改进

## Future Enhancements

- [ ] Body optimization: 不仅 reject，还建议改进内容
- [ ] Scenario-based filtering: 按业务场景过滤
- [ ] A/B testing: 对比应用前后的分数
- [ ] Web dashboard: 可视化趋势和批量审批
- [ ] Continuous learning: 每次 pipeline 后自动运行分析

## Related Files

- `scripts/analyze_clause_iteration.py` - 分析器
- `scripts/auto_clause_iteration.py` - 执行器
- `src/eval/pipeline_store.py` - Pipeline 数据存储
- `src/clauses/tag_review.py` - Tag review 操作
- `openspec/changes/clause-tag-self-iteration/` - 设计文档

---

*Last updated: 2026-08-04*
