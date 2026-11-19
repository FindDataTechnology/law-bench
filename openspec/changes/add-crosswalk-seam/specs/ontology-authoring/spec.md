## ADDED Requirements

### Requirement: crosswalk 不参与关系图谱与端点闭合

crosswalk 不是关系。系统 SHALL 在关系图谱遍历、关系端点闭合校验、关系参照完整率统计三处排除 `kind='crosswalk'` 的单元。

关系的两个端点校验口径 SHALL 保持不变：起点与终点仍须是本域已存在且未软删的实体。本变更 MUST NOT 以 crosswalk 的存在放宽该约束。

#### Scenario: 端点闭合校验不受影响
- **WHEN** 创建一条关系，其端点在本域不存在但在别层有 crosswalk 指向
- **THEN** 关系创建仍被拒绝并说明端点不存在

#### Scenario: 参照完整率不含 crosswalk
- **WHEN** 某域有 10 条关系与 20 条 crosswalk
- **THEN** 关系参照完整率的分母为 10，不含 crosswalk

## MODIFIED Requirements

### Requirement: 未整理状态必须显式可见

「本体」区 SHALL 区分「模板声明的词表」与「实际整理的内容」，并 SHALL 显式标出零实例的声明类型与疑似测试数据，SHALL NOT 把存在几条记录渲染成「本体已就绪」。

本变更新增：crosswalk 的「待复核」状态 SHALL 在同一读面按同一纪律显式标出，MUST NOT 因它是另一种 kind 而改用另一套状态词汇——「待复核 / 已复核」与「未整理 / 已整理」SHALL 由同一处判定派生。

#### Scenario: 声明了但没用过
- **WHEN** 模板声明 5 个实体类型而其中 3 个没有任何实例
- **THEN** 页面把这 3 个类型列为覆盖缺口，而不是显示为正常

#### Scenario: 冒烟数据被标出
- **WHEN** 某域的单位里包含明显来自冒烟测试的键
- **THEN** 页面标注其为测试数据，提示清理，不把它们计入「已整理」

#### Scenario: 状态词汇单一来源
- **WHEN** 同一单元在关系读面与映射读面同时出现
- **THEN** 两处显示的复核状态一致，不存在一处说已复核、另一处说待复核
