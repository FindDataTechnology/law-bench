# Design - Auto-Iteration Pipeline

## Architecture

```
现有 pipeline (pipeline_run):
  START -> generate -> fill -> evaluate -> check -> [improve -> generate]* -> store -> END

新 pipeline (auto_pipeline_run):
  START -> generate -> fill -> evaluate -> check -> [improve -> generate]* -> store -> learn -> END
                                                                        ↑
                                                              新增 learn 节点
```

复用现有所有节点（generate/fill/evaluate/check/improve/store），仅追加 learn 节点。

## Components

### 1. Learn Node (`pipeline/learn.py`)

**职责**: 在 store 之后自动应用高置信度 clause 改进。

**逻辑**:
1. 收集当前 run 的 recommendations（action='reject'）
2. 聚合历史 50 次 pipeline_runs 中同 contract_type 的 reject 推荐
3. 合并计数: `total = current_count + historical_count`
4. 对每个达到阈值 (`AUTO_REJECT_THRESHOLD`, 默认 3) 的 custom clause:
   - 验证是 custom clause（base/tagged 不动）
   - 调用 `bulk_review(cid, 'rejected')` 标记为 rejected
   - 记录到 `learn_applied` 列表
5. 将 `learn_applied` 回写到 pipeline_runs 行

**安全机制**:
- 只 reject custom clauses（`_is_custom_clause` 检查）
- fail-safe: 任何异常被捕获，不中断 pipeline
- 阈值可通过环境变量配置

### 2. Auto Graph (`pipeline/auto_graph.py`)

复用 `graph.py` 的所有节点和 `_route` 路由函数，构建新 graph:
- 所有边与标准 pipeline 相同
- 仅在 `store` 后加 `store -> learn -> END`

### 3. MCP Tool (`tools/auto_pipeline.py`)

`auto_pipeline_run` - 与 `pipeline_run` 相同的参数签名，返回多一个 `learn_applied` 字段。

## Data Flow

```
recommendations (当前 run)
        +
recommendations (历史 50 runs, 同 contract_type)
        ↓
   聚合计数 per clause_id
        ↓
   total >= AUTO_REJECT_THRESHOLD (3)?
        ↓ yes
   _is_custom_clause(cid)?
        ↓ yes
   bulk_review(cid, 'rejected')  →  clauses.tag_review 全部置为 rejected
        ↓
   记录到 learn_applied[]
        ↓
   UPDATE pipeline_runs SET learn_applied = ...
```

## DB Schema

新增列（additive, idempotent）:
```sql
ALTER TABLE IF EXISTS pipeline_runs
  ADD COLUMN IF NOT EXISTS learn_applied JSONB NOT NULL DEFAULT '[]'::jsonb;
```

通过 `_ADDITIVE_COLUMNS` 机制自动迁移，无需手动 SQL。

## PipelineState 扩展

```python
class PipelineState(TypedDict, total=False):
    # ... existing fields ...
    learn_applied: list  # 新增：learn 节点自动应用的记录
```

## Configuration

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `AUTO_REJECT_THRESHOLD` | 3 | 累计 reject 推荐次数达到此值才自动执行 |

## 与手动流程的关系

- **手动 pipeline** (`pipeline_run`): 只记录不执行，保持不变
- **自动 pipeline** (`auto_pipeline_run`): store 后自动 learn
- **离线脚本** (`scripts/analyze_clause_iteration.py` + `auto_clause_iteration.py`): 手动批量分析+执行

三者共享同一套 `bulk_review` / `clause_review` 底层操作，互不冲突。

## Verification

1. ✅ imports 正常
2. ✅ schema 迁移成功 (learn_applied 列已创建)
3. ✅ learn_node 逻辑正确 (7263: 2 current + 2 historical = 4 ≥ 3 → rejected)
4. ✅ auto_pipeline_run tool 已注册 (45 tools total)
5. ⏳ 端到端测试: 运行 `auto_pipeline_run(contract_type="employment")`
