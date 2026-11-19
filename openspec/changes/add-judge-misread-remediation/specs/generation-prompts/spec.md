# generation-prompts Specification（delta）

## Purpose

判官评分链 prompt 修复走既有版本化域：新增评分链 prompt 类型的版本行，provenance 记录修复动因；既有存储/种子/查询/版本需求全部不变。

## ADDED Requirements

### Requirement: 评分链 prompt 版本化

判官评分链 prompt（judge scoring task prompt）SHALL 以新版本行落入既有 prompt 存储域（沿 `Prompt Provenance` 与 `Prompt Type (Variant Lineage)` 既有需求）：修复版本不覆盖历史行；provenance SHALL 记录修复动因（`add-judge-misread-remediation`）与生效范围（judge scoring）；回滚 = 查询既有版本行。

#### Scenario: 修复版本落库
- **WHEN** 修复后的评分链 prompt 落库
- **THEN** 新版本行可查，历史行不变，provenance 记录动因与范围

#### Scenario: 按版本回滚
- **WHEN** 需要回退到修复前行为
- **THEN** 查询并启用既有版本行即可，无数据迁移
