# Pipeline Architecture

本文档描述 law-bench 的 pipeline 架构、并发安全规则和最佳实践。

## Overview

law-bench 提供三个 pipeline，用于合同生成、评估和条款迭代优化：

```
┌─────────────────────────────────────────────────────────────────┐
│  Pipeline 1: self_heal_pipeline_run (标准自愈)                    │
├─────────────────────────────────────────────────────────────────┤
│  generate → fill → evaluate → check → [improve]* → store → END  │
│                                                                  │
│  用途: 单次合同生成，自愈循环优化内容                               │
│  并发: ✅ 安全 (只读 clauses 表)                                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Pipeline 2: auto_reject_pipeline_run (自动 reject)               │
├─────────────────────────────────────────────────────────────────┤
│  generate → fill → evaluate → check → [improve]* → store         │
│ ↓        │
│                                                       learn      │
│                                              (自动 reject 差条款) │
│                                                         ↓        │
│                                                        END       │
│                                                                  │
│  用途: 批量跑合同，自动淘汰差条款                                   │
│  并发: ✅ 安全 (learn 节点幂等)                                    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Pipeline 3: tag_iteration_suggest + tag_iteration_apply          │
├─────────────────────────────────────────────────────────────────┤
│  suggest: generate → fill → evaluate → check → [improve]* →     │
│           store → suggest_retag → END                            │
│                                                                  │
│  apply:   apply_retag → re-evaluate → [rollback if worse] → END │
│                                                                  │
│  用途: 分析条款 tag 是否合理，人工审批后应用，自动验证效果           │
│  并发:                                                           │
│    - suggest: ✅ 安全 (只读)                                      │
│    - apply:   ❌ 必须串行 (pg_advisory_lock 保护)                 │
└─────────────────────────────────────────────────────────────────┘
```

## Pipeline Details

### 1. self_heal_pipeline_run

标准自愈 pipeline，用于单次合同生成。

**工作流：**
1. `generate`: 根据 contract_type 和 tags 生成合同骨架
2. `fill`: LLM 填充 {{slot}} 占位符
3. `evaluate`: 使用 rubric 评估合同质量
4. `check`: 检查是否 all_pass 或达到 max_iterations
5. `improve`: 如果评估失败，分析失败原因，排除薄弱的 custom clauses
6. `store`: 持久化最佳结果到 pipeline_runs 表

**并发安全：** ✅ 安全
- 只读 clauses 表
- 多个子代理可以同时运行

**示例：**
```python
result = self_heal_pipeline_run(
    contract_type="sale",
    stance="balanced",
    max_iterations=3
)
```

### 2. auto_reject_pipeline_run

自动 reject pipeline，在 self_heal 基础上增加 learn 节点。

**工作流：**
1. 执行 self_heal pipeline 的所有步骤
2. `learn`: 聚合当前和历史 recommendations
   - 统计每个 clause 被 reject 的次数
   - 达到阈值（默认 3 次）的 clause 自动标记为 rejected
   - 只 reject custom clauses，不动 base/tagged

**并发安全：** ✅ 安全
- learn 节点是幂等的（多次 reject 同一 clause 结果一样）
- 多个子代理可以同时运行

**示例：**
```python
result = auto_reject_pipeline_run(
    contract_type="employment",
    stance="balanced",
    max_iterations=2
)
# result['learn_applied'] 包含被自动 reject 的 clauses
```

### 3. tag_iteration_suggest + tag_iteration_apply

Tag 迭代 pipeline，分两步：建议和应用。

**Step 1: tag_iteration_suggest**

分析失败的 clauses，LLM 建议 tag 修改。

**工作流：**
1. 执行 self_heal pipeline 的所有步骤
2. `suggest_retag`: LLM 分析失败 clauses 的 tags
   - 检查 scenario/stance/strength 是否合理
   - 返回建议列表：`[{clause_id, current_tags, suggested_tags, reason}]`

**并发安全：** ✅ 安全（只读）

**示例：**
```python
result = tag_iteration_suggest(
    contract_type="sale",
    stance="pro_buyer",
    max_iterations=2
)
suggestions = result['retag_suggestions']
```

**Step 2: tag_iteration_apply**

应用审批后的 tag 修改，自动验证效果。

**工作流：**
1. 获取 advisory lock（串行化）
2. 保存原始 tags（用于 rollback）
3. 应用新 tags
4. 重新评估合同
5. 如果分数下降，自动 rollback
6. 释放 advisory lock

**并发安全：** ❌ 必须串行
- 使用 `pg_advisory_lock(hashtext('tag_iteration'))` 保护
- 同时只能有一个 apply 运行
- 其他 pipeline 可以同时运行（不受影响）

**示例：**
```python
# 人工审批后
approved = [
    {"clause_id": 7266, "suggested_tags": {"scenario": "劳动合同"}}
]
result = tag_iteration_apply(
    approved_suggestions=approved,
    contract_type="employment",
    stance="balanced"
)
# result['rolled_back'] 表示是否回滚
# result['score_before'], result['score_after'] 对比分数
```

## Concurrency Rules

| Pipeline | 并发安全 | 原因 |
|---------|---------|------|
| `self_heal_pipeline_run` | ✅ | 只读 clauses 表 |
| `auto_reject_pipeline_run` | ✅ | learn 节点幂等 |
| `tag_iteration_suggest` | ✅ | 只读 clauses 表 |
| `tag_iteration_apply` | ❌ | 修改 clauses.tags，需要串行 |

**最佳实践：**
- 多个子代理可以同时跑 `self_heal_pipeline_run` 或 `auto_reject_pipeline_run`
- `tag_iteration_apply` 必须单独运行，不能与其他 apply 同时
- `tag_iteration_suggest` 可以并发，但 apply 必须串行

## Data Flow

```
clauses 表
    ↓ (read)
generate → fill → evaluate → check → [improve]* → store
                                                        ↓
                                              pipeline_runs 表
                                                        ↓
                                              learn_node (可选)
                                                        ↓
                                              bulk_review(clause_id, 'rejected')
                                                        ↓
                                              clauses.tag_review 更新
```

## Error Handling

所有 pipeline 都有 fail-safe 机制：
- LLM 调用失败：返回空结果，不 crash
- DB 连接失败：重试 3 次
- Advisory lock 超时：30 秒后报错

## Performance

- `self_heal_pipeline_run`: 1-3 分钟（取决于 max_iterations）
- `auto_reject_pipeline_run`: 1-3 分钟（同上）
- `tag_iteration_suggest`: 1-3 分钟（同上）
- `tag_iteration_apply`: 2-6 分钟（需要两次评估）

## Migration Notes

旧名称（已废弃，但保留向后兼容）：
- `pipeline_run` → `self_heal_pipeline_run`
- `auto_pipeline_run` → `auto_reject_pipeline_run`

新代码请使用新名称。

---

*Last updated: 2026-08-04*
