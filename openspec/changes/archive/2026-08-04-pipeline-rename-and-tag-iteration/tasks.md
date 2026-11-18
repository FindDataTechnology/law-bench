# Tasks: Pipeline Rename and Tag Iteration

## Task 1: Rename self_heal_pipeline
- [x] 修改 `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/pipeline/graph.py`
  - [x] 添加模块注释说明这是标准自愈 pipeline
  - [x] 重命名函数 `run_pipeline` → `run_self_heal_pipeline`
  - [x] 重命名 `build_graph` → `build_self_heal_graph`
- [x] 修改 `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/tools/pipeline.py`
  - [x] 重命名 MCP tool `pipeline_run` → `self_heal_pipeline_run`
  - [x] 更新 docstring 说明用途
- [x] 更新所有引用点

## Task 2: Rename auto_reject_pipeline
- [x] 修改 `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/pipeline/auto_graph.py`
  - [x] 添加模块注释说明这是自动 reject pipeline
  - [x] 重命名函数 `run_auto_pipeline` → `run_auto_reject_pipeline`
  - [x] 重命名 `build_auto_graph` → `build_auto_reject_graph`
- [x] 修改 `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/tools/auto_pipeline.py`
  - [x] 重命名 MCP tool `auto_pipeline_run` → `auto_reject_pipeline_run`
  - [x] 更新 docstring 说明用途
- [x] 更新所有引用点

## Task 3: Implement tag_iteration_suggest
- [x] 创建 `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/pipeline/suggest_retag.py`
  - [x] 实现 `suggest_retag_node(state)` 函数
  - [x] 实现 LLM prompt 构建（分析失败 clauses 的 tags）
  - [x] 实现 LLM 响应解析（返回建议列表）
- [x] 创建 `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/pipeline/tag_iteration_graph.py`
  - [x] 实现 `build_tag_iteration_graph()` 函数
  - [x] 实现 `run_tag_iteration_pipeline()` 函数
  - [x] 图结构：generate → fill → evaluate → check → [improve]* → store → suggest_retag → END
- [x] 创建 `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/tools/tag_iteration.py`
  - [x] 实现 MCP tool `tag_iteration_suggest`
  - [x] 参数：contract_type, tags, stance, rubric, task_desc, max_iterations
  - [x] 返回：suggestions 列表

## Task 4: Implement tag_iteration_apply
- [x] 扩展 `tag_iteration.py`
  - [x] 实现 MCP tool `tag_iteration_apply`
  - [x] 参数：approved_suggestions (list of {clause_id, new_tags})
  - [x] 实现 `pg_advisory_lock` 保护（防止并发）
  - [x] 实现 save_original_tags 逻辑
  - [x] 实现 apply_retag 逻辑
  - [x] 实现 re-evaluate 逻辑
  - [x] 实现 rollback 逻辑（分数下降时恢复）
  - [x] 返回：applied, rolled_back, score_before, score_after

## Task 5: Update PipelineState
- [x] 修改 `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/pipeline/graph.py`
  - [x] 添加 `retag_suggestions: list[dict]` 字段
  - [x] 添加 `retag_approved: list[dict]` 字段
  - [x] 添加 `retag_original_tags: dict[int, dict]` 字段
  - [x] 添加 `retag_applied: list[dict]` 字段
  - [x] 添加 `retag_rolled_back: bool` 字段

## Task 6: Update server.py
- [x] 修改 `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/server.py`
  - [x] 导入 `tag_iteration` 模块
  - [x] 注册新的 MCP tools

## Task 7: Documentation
- [x] 更新 `fd-coding-law-bench-mcp/README.md`
  - [x] 说明三个 pipeline 的用途和并发规则
  - [x] 添加使用示例
- [x] 创建 `docs/pipeline-architecture.md`
  - [x] 架构图
  - [x] 并发安全说明
  - [x] 最佳实践

## Task 8: Testing
- [x] 测试 self_heal_pipeline_run（重命名后）
- [x] 测试 auto_reject_pipeline_run（重命名后）
- [x] 测试 tag_iteration_suggest
- [x] 测试 tag_iteration_apply（含 rollback）
- [x] 测试并发场景（多个子代理同时跑 self_heal）
- [x] 测试 advisory lock（tag_iteration_apply 串行化）

## Task 9: Migration
- [x] 更新现有代码中对 `pipeline_run` 的引用
- [x] 更新现有代码中对 `auto_pipeline_run` 的引用
- [ ] 更新测试文件
- [ ] 更新文档

## Task 10: Final Verification
- [x] 所有 MCP tools 可正常调用
- [ ] 并发场景测试通过
- [ ] 文档完整
- [x] 无遗留的旧名称引用
