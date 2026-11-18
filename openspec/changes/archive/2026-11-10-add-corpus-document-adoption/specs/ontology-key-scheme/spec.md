## ADDED Requirements

### Requirement: 语料切出的条款键必须与既有条款键同形

从语料目录切分产出的条款键 SHALL 与既有条款键规则完全一致（`<law_key>#<clause_no>`，`clause_no` 为纯条款号）。系统 MUST NOT 引入第二种条款键形状（例如带块号、带库前缀、带文档 id 的复合键）。

#### Scenario: 两条来源同一部法
- **WHEN** 同一部法既被抽取提名又被目录切分取入
- **THEN** 两者得到同一个键，不会并存两份条款单位

#### Scenario: 键里不带库标识
- **WHEN** 从 `law-library` 取入某文档第 12 条
- **THEN** 键是 `<law_key>#第12条`，不含库名或来源名
