# domain-workspace Specification（delta）

## Purpose

C2 创作台成为域租户隔离的新消费方：增「域内内容隔离」的可观测面。既有租户隔离语义不变。

## ADDED Requirements

### Requirement: 域内内容隔离的创作面消费

创作台对域内容的全部读写 SHALL 经域成员身份执法：写操作要求域内 expert 及以上角色（annotator 只读），读操作要求任一域内角色；平台 `admin` scope 沿既有合成规则直通；创作台 SHALL NOT 提供任何绕过域成员检查的内容访问路径。

#### Scenario: 标注员只读
- **WHEN** 域内 annotator 角色成员尝试提交实体创作
- **THEN** 写入被拒并报明角色不足；其读取域内容不受影响

#### Scenario: 专家读写边界
- **WHEN** 域内 expert 角色成员提交实体/关系创作与修改
- **THEN** 操作执行且留痕；其尝试管理成员或邀请时仍被拒（lead/admin 专属，C1 语义不变）
