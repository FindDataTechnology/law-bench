# Design: Pipeline Rename and Tag Iteration

## Overview

重命名现有 pipelines 使其更清晰，新增 tag_iteration pipeline 实现自动改 tag + 测试。

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Pipeline 1: self_heal_pipeline_run (标准自愈)                    │
├─────────────────────────────────────────────────────────────────┤
│  generate → fill → evaluate → check → [improve]* → store → END  │
│                                                                  │
│  用途: 单次合同生成，自愈循环优化内容                               │
│  并发: ✅ 可以多个子代理同时跑                                     │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Pipeline 2: auto_reject_pipeline_run (自动 reject)               │
├─────────────────────────────────────────────────────────────────┤
│  generate → fill → evaluate → check → [improve]* → store         │
│                                                         ↓        │
│                                                       learn      │
│                                              (自动 reject 差条款) │
│                                                         ↓        │
│                                                        END       │
│                                                                  │
│  用途: 批量跑合同，自动淘汰差条款                                   │
│  并发: ✅ 可以多个子代理同时跑 (learn_node 幂等)                   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Pipeline 3: tag_iteration_suggest (建议改 tag)                   │
├─────────────────────────────────────────────────────────────────┤
│  generate → fill → evaluate → check → [improve]* → store         │
│                                                         ↓        │
│                                                   suggest_retag  │
│                                              (LLM 分析建议改 tag) │
│                                                         ↓        │
│                                                        END       │
│                                                                  │
│  返回: [{clause_id, current_tags, suggested_tags, reason}]       │
│  用途: 分析条款 tag 是否合理                                       │
│  并发: ✅ 可以多个子代理同时跑 (只读)                              │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Pipeline 4: tag_iteration_apply (应用 tag 修改)                  │
├─────────────────────────────────────────────────────────────────┤
│  apply_retag → re-evaluate → [rollback if worse] → END           │
│                                                                  │
│  用途: 人工审批后应用 tag 修改，自动验证效果                        │
│  并发: ❌ 必须串行 (用 pg_advisory_lock 保护)                     │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Pipeline Rename

| 当前名称 | 新名称 | 文件 |
|---------|--------|------|
| `pipeline_run` | `self_heal_pipeline_run` | `tools/pipeline.py` → `tools/self_heal_pipeline.py` |
| `auto_pipeline_run` | `auto_reject_pipeline_run` | `tools/auto_pipeline.py` |

**向后兼容**: 保留旧名称作为别名，标记为 deprecated。

### 2. tag_iteration_suggest

**新增文件**: `tools/tag_iteration.py`, `pipeline/tag_iteration_graph.py`

**suggest_retag 节点逻辑**:

```python
def suggest_retag_node(state):
    # 1. 获取失败的 clauses
    failing_clauses = get_failing_clauses(state)
    
    # 2. LLM 建议新 tags
    suggestions = []
    for clause in failing_clauses:
        suggested = llm_suggest_tags(
            clause_body=clause['body'],
            current_tags=clause['tags'],
            failing_reasons=state['eval_result']['failing_criteria']
        )
        if suggested['current_tags'] != suggested['suggested_tags']:
            suggestions.append({
                'clause_id': clause['id'],
                'section': clause['section'],
                'current_tags': suggested['current_tags'],
                'suggested_tags': suggested['suggested_tags'],
                'reason': suggested['reason']
            })
    
    return {'retag_suggestions': suggestions}
```

**LLM Prompt**:

```
你是合同条款标签分析师。一份合同评估失败，失败原因：
{failing_criteria}

以下条款被用于该合同：
{clauses_with_tags}

请分析每个条款的 tags 是否合理：
1. 条款内容涉及的业务场景 (scenario) 是否与 tag 匹配？
2. 条款的利益倾向 (stance) 是否与合同要求一致？
3. 条款的强度 (strength) 是否合适？

输出 JSON: [{
  clause_id: int,
  section: str,
  current_tags: {...},
  suggested_tags: {...},
  reason: "为什么建议改"
}]
```

### 3. tag_iteration_apply

**MCP Tool**: `tag_iteration_apply(approved_suggestions)`

**逻辑**:

```python
@mcp.tool(tags={"tag_iteration"})
async def tag_iteration_apply(
    approved_suggestions: list[dict],
) -> dict:
    """应用审批后的 tag 修改，自动验证效果。"""
    
    def _go():
        conn = connect()
        try:
            # 1. 获取排他锁
            conn.execute("SELECT pg_advisory_lock(hashtext('tag_iteration'))")
            
            # 2. 保存原始 tags (for rollback)
            original_tags = {}
            for sug in approved_suggestions:
                clause = get_custom_clause(sug['clause_id'])
                original_tags[sug['clause_id']] = clause['tags']
            
            # 3. 应用新 tags
            for sug in approved_suggestions:
                update_clause(sug['clause_id'], {'tags': sug['suggested_tags']})
            
            # 4. 重新生成合同并评估
            new_contract = generate_contract(...)
            new_eval = evaluate_contract(new_contract)
            
            # 5. 对比分数
            old_score = get_baseline_score(...)
            new_score = new_eval['score']
            
            if new_score >= old_score:
                # 保留修改
                return {
                    'applied': approved_suggestions,
                    'rolled_back': False,
                    'old_score': old_score,
                    'new_score': new_score,
                    'improvement': new_score - old_score
                }
            else:
                # Rollback
                for clause_id, tags in original_tags.items():
                    update_clause(clause_id, {'tags': tags})
                return {
                    'applied': approved_suggestions,
                    'rolled_back': True,
                    'old_score': old_score,
                    'new_score': new_score,
                    'regression': old_score - new_score
                }
        finally:
            conn.execute("SELECT pg_advisory_unlock(hashtext('tag_iteration'))")
            conn.close()
    
    return await anyio.to_thread.run_sync(_go)
```

### 4. PipelineState 扩展

```python
class PipelineState(TypedDict, total=False):
    # ... existing fields ...
    
    # tag_iteration fields
    retag_suggestions: list[dict]      # suggest_retag 输出
    retag_approved: list[dict]         # 用户审批后的建议
    retag_original_tags: dict[int, dict]  # 原始 tags (for rollback)
    retag_applied: list[dict]          # 实际应用的修改
    retag_rolled_back: bool            # 是否回滚
```

## Concurrency Rules

| Pipeline | 修改 clauses 表？ | 并发安全？ | 锁机制 |
|---------|-----------------|----------|--------|
| `self_heal_pipeline_run` | 否 (只读) | ✅ 安全 | 无 |
| `auto_reject_pipeline_run` | 是 (tag_review) | ✅ 安全 | 无 (幂等) |
| `tag_iteration_suggest` | 否 (只读) | ✅ 安全 | 无 |
| `tag_iteration_apply` | 是 (tags) | ❌ 不安全 | `pg_advisory_lock` |

## File Structure

```
fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/
├── pipeline/
│   ├── graph.py                    # self_heal_pipeline (rename, add comments)
│   ├── auto_graph.py               # auto_reject_pipeline (rename, add comments)
│   ├── tag_iteration_graph.py      # NEW: tag_iteration pipelines
│   ├── suggest_retag.py            # NEW: LLM tag suggestion logic
│   ├── learn.py                    # existing: auto-reject logic
│   └── ...
├── tools/
│   ├── self_heal_pipeline.py       # NEW: renamed from pipeline.py
│   ├── auto_reject_pipeline.py     # NEW: renamed from auto_pipeline.py
│   ├── tag_iteration.py            # NEW: tag_iteration_suggest + tag_iteration_apply
│   ├── pipeline.py                 # DEPRECATED: alias to self_heal_pipeline
│   ├── auto_pipeline.py            # DEPRECATED: alias to auto_reject_pipeline
│   └── ...
```

## Migration Plan

1. **Phase 1: Rename existing pipelines**
   - Rename `pipeline.py` → `self_heal_pipeline.py`
   - Rename `auto_pipeline.py` → `auto_reject_pipeline.py`
   - Add backward-compatible aliases
   - Add docstrings explaining each pipeline

2. **Phase 2: Implement tag_iteration_suggest**
   - Create `tag_iteration_graph.py`
   - Create `suggest_retag.py`
   - Create `tag_iteration_suggest` MCP tool

3. **Phase 3: Implement tag_iteration_apply**
   - Create `tag_iteration_apply` MCP tool with advisory lock
   - Implement rollback logic

4. **Phase 4: Testing**
   - Test each pipeline independently
   - Test concurrency scenarios
   - Test rollback logic

## Success Metrics

1. **Pipeline clarity**: 用户能清楚区分不同 pipeline 的用途
2. **Tag iteration accuracy**: LLM 建议的 tag 修改能提升评估分数
3. **Concurrency safety**: 多个子代理可以同时跑 pipeline 而不冲突
4. **Rollback effectiveness**: 分数下降时能正确回滚
