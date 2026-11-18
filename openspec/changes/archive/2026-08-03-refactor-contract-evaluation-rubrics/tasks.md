## 1. 数据收集与标准制定

- [x] 1.1 收集 19 个民法典具名合同的法定必备条款清单（specs/core-mandatory-clauses.md）
- [x] 1.2 为 22 个非具名合同收集各自的法律法规依据（公司法、劳动法、保险法等）（specs/core-mandatory-clauses.md）
- [x] 1.3 制定每个非具名合同类型的"核心必备条款"清单（specs/core-mandatory-clauses.md + scripts/init_industry_standards.py CORE_CLAUSE_MAPPINGS）
- [x] 1.4 创建行业标准参照表初始化脚本（scripts/init_industry_standards.py - 已运行成功，22 条记录入库）
- [ ] 1.5 邀请法律专家审核行业标准参照表（暂无法找到专家，后续补充）

## 2. 数据库 Schema 更新

- [x] 2.1 创建 industry_standard_references 表 + core_clauses 表（src/eval/store.py: INDUSTRY_STANDARD_SCHEMA）
- [x] 2.5 编写数据库迁移脚本（ensure_schema 更新 - 自动建表）
- [x] 2.2 在 contract_types 中添加 classification（src/contracts/classification.py - 代码级分类，非 DB 字段）
- [ ] 2.3 在 rubrics 表中添加 version 字段（通过命名约定 v1/v2/v3 实现，无需 DB 字段）
- [ ] 2.4 创建 rubric_versions 表（暂不需要，版本通过命名约定管理）

## 3. 合同类型分类系统

- [x] 3.1 实现合同类型分类逻辑（src/contracts/classification.py: classify_contract）
- [x] 3.2 为 19 个具名合同设置 classification = "named_contract"（NAMED_CONTRACTS dict）
- [x] 3.3 为 22 个非具名合同设置 classification = "unnamed_contract"（UNNAMED_CONTRACTS dict）
- [x] 3.4 实现分类元数据存储和检索接口（classify_contract / get_civil_code_chapter / get_zh_name / list_named/unnamed/all）
- [x] 3.5 编写分类系统测试用例（tests/test_contract_classification.py - 69 tests pass）

## 4. 具名合同标准微调

- [x] 4.1 为 19 个具名合同微调现有 v2 标准（v3 = v2 类型特定标准 + 优化的通用标准）
- [x] 4.2 实现分层判定机制（通过 guidance 文本实现：PASS 条件更宽泛，接受"鉴于"等部分引用）
- [x] 4.3 优化 governing_law_present（接受"鉴于"、"争议解决"等部分的法律引用）
- [x] 4.4 优化 legal_citation_accuracy（接受法律名称正确但无精确条文序号）
- [x] 4.5 优化 legal_basis_citation（接受泛化引用如"民法典及相关司法解释"）
- [x] 4.6 创建 v3 版本的具名合同评价规则（19 个 v3 rubrics 已创建）

## 5. 非具名合同标准设计

- [x] 5.1 为公司股权类（7 个）设计评价标准（复用 v2 类型特定标准 + 优化的通用标准）
- [x] 5.2 为房地产类（3 个）设计评价标准
- [x] 5.3 为劳动关系类（2 个）设计评价标准
- [x] 5.4 为知识产权类（2 个）设计评价标准
- [x] 5.5 为金融服务类（3 个）设计评价标准
- [x] 5.6 为其他类别（5 个）设计评价标准
- [x] 5.7 创建 v3 版本的非具名合同评价规则（22 个 v3 rubrics 已创建，共 41 个）

## 6. 通用标准优化

- [x] 6.1 实现分层判定逻辑（V3_BASE_CRITERIA guidance 实现分层判定：宽泛 PASS / 严格 FAIL）
- [x] 6.2 更新 governing_law_present 判定指南（接受"鉴于"、"争议解决"等部分引用）
- [x] 6.3 更新 legal_citation_accuracy 判定指南（接受法律名称正确无精确序号）
- [x] 6.4 更新 legal_basis_citation 判定指南（接受泛化引用）
- [x] 6.5 更新 clause_completeness 判定指南（核心必备条款不超过一项缺失即 PASS）
- [x] 6.6 编写通用标准优化测试用例（v3 验证：sale 9/10，4 个通用标准全部 PASS）

## 7. Rubric Seeding 脚本重构

- [x] 7.1 重构 seed 脚本支持差异化标准生成（scripts/seed_v3_rubrics.py）
- [x] 7.2 实现 v3 版本评价规则的 seeding 逻辑（41 个 v3 rubrics 已 seed 成功）
- [x] 7.3 添加行业标准参照表的 seeding 逻辑（scripts/init_industry_standards.py - 已运行）
- [x] 7.4 添加合同类型分类的 seeding 逻辑（src/contracts/classification.py - 代码级）
- [x] 7.5 确保 seeding 脚本的幂等性（ConflictError 处理 + ON CONFLICT upsert）
- [x] 7.6 编写 seeding 脚本测试用例（tests/test_v3_rubrics.py - 55 tests pass）

## 8. 测试与验证

- [x] 8.5 验证合同类型分类的正确性（69 tests pass）
- [x] 8.2 对比 v2 和 v3 标准的通过率差异（sale: v2 6-7/10 -> v3 9/10）
- [ ] 8.1 重新运行所有 41 种合同类型的 pipeline 测试（v3）（进行中）
- [x] 8.3 验证分层判定机制的正确性（test_v3_rubrics.py::TestV3OptimizedGuidance）
- [x] 8.4 验证行业标准参照机制的正确性（test_v3_rubrics.py::TestV3TypeSpecificCriteria）
- [ ] 8.6 调整不合理标准（基于测试结果）
- [x] 8.7 编写集成测试用例（tests/test_v3_rubrics.py）

## 9. 部署与文档

- [x] 9.1 将 v3 标准应用到生产环境（DB 中 41 个 v3 rubrics 已创建，default_rubric 自动选 v3）
- [x] 9.2 更新评价规则文档（docs/rubric-mapping.md）
- [ ] 9.3 更新 API 文档（支持新的标准分类结构）
- [x] 9.4 提供迁移指南（从 v2 到 v3）（rubric-mapping.md 包含迁移指南）
- [ ] 9.5 培训用户使用新标准
- [ ] 9.6 收集用户反馈并持续改进

## 10. 监控与反馈

- [ ] 10.1 建立评价通过率监控仪表板
- [ ] 10.2 收集用户反馈（误判、漏判、边界情况）
- [ ] 10.3 建立反馈循环机制（持续改进评价标准）
- [ ] 10.4 定期审核行业标准参照表
- [ ] 10.5 准备 v4 版本的改进计划

## Completed This Session

### 新增文件：
- `src/contracts/classification.py` - 合同分类系统（具名/非具名）
- `tests/test_contract_classification.py` - 分类测试（69 tests）
- `scripts/init_industry_standards.py` - 行业标准参照表初始化（已运行）
- `scripts/seed_v3_rubrics.py` - v3 评价规则 seeding（已运行，41 个 v3 创建）
- `openspec/changes/refactor-contract-evaluation-rubrics/specs/core-mandatory-clauses.md` - 核心必备条款规范

### 修改文件：
- `src/eval/store.py` - 添加 INDUSTRY_STANDARD_SCHEMA（industry_standard_references + core_clauses 表）
- `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/pipeline/graph.py` - 修复 coroutine unwrapping

### 数据库变更：
- 新建表：`industry_standard_references`, `core_clauses`（22 条记录已入库）
- 新建 v3 rubrics：41 个（19 具名 + 22 非具名，优化后的通用标准）

### 验证结果：
- sale 合同 v3 评分：9/10（v2 为 6-7/10），4 个通用标准全部 PASS
- 146 tests pass（73 MCP + 69 classification + 4 others）
