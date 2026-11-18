## ADDED Requirements

### Requirement: 抽取支持非向量文本源

抽取 SHALL 能从「按表读取的文本源」取样（表名 + 列映射），SHALL NOT 要求该语料先被向量化。取样结果 SHALL 与原 qdrant 取样同形（`chunk_id`/`text`/`title`/来源），使下游校验与键方案无需分支。

#### Scenario: 裁判要点按表取样
- **WHEN** 语料源声明为 `text-table`，表 `guide_cases`，文本列 `gist`
- **THEN** 取样返回该表的行，`title` 取案例标题，`chunk_id` 取案例编号

#### Scenario: 列缺失时报错而不是空跑
- **WHEN** 声明的文本列在表里不存在
- **THEN** 取样报错并指明缺的列，不返回空列表冒充「没有语料」

### Requirement: 概念候选的语料面提示

抽取提示词 SHALL 能按语料形态调整：对裁判要点类语料，要求模型优先产出概念与「概念→法条」依据，而不是条款编号。

#### Scenario: 裁判要点产出概念而非条款
- **WHEN** 对裁判要点语料运行抽取
- **THEN** 产出以 `concept` 为主，且条款类候选显著减少
