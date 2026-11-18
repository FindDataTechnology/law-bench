# domain-lifecycle Specification

## Purpose
域是长期资产，但**不是每个域都值得长期在役**：试验性的、废弃的、建错的域需要一个体面的退场方式，而不是「永久占着名录」或「连同内容一起删掉」。归档就是这个动作——它让域从运营面上消失，同时保留它积累的一切。

## Requirements

### Requirement: 归档是软退场

系统 SHALL 允许平台管理员归档一个域。归档 SHALL 记录时间戳并保留该域的全部数据（成员、订阅、知识单元、评测记录、提案）；SHALL NOT 级联删除任何关联行。归档后该域 SHALL NOT 出现在名录、缺口矩阵与域切换器中，SHALL NOT 可被检索（其内容不再属于任何可达域）。

#### Scenario: 归档后从运营面消失
- **WHEN** 管理员归档域 `trial-x`
- **THEN** 名录、缺口矩阵、切换器里都不再出现它；它原有的知识单元、订阅、成员记录仍在库里

#### Scenario: 归档不影响其它域
- **WHEN** 归档一个子域
- **THEN** 父域与兄弟域的检索范围、缺口计数完全不变

### Requirement: 归档可恢复

系统 SHALL 允许管理员恢复已归档的域。恢复后该域 SHALL 回到归档前的状态：出现在名录、缺口矩阵按原数据计算、订阅与成员照旧生效。

#### Scenario: 恢复即回原样
- **WHEN** 管理员恢复 `trial-x`
- **THEN** 它重新出现在名录，其缺口与归档前一致（数据从未被改动）

### Requirement: 归档不释放 key

归档 SHALL NOT 释放该域的 key：`UNIQUE(key)` 继续有效，同名域 SHALL NOT 能被再次创建。这避免「新域继承旧域引用」的混淆——历史记录里的 key 必须始终指向同一个域。

#### Scenario: key 不能被复用
- **WHEN** 域 `trial-x` 已归档，管理员尝试再建一个 key 为 `trial-x` 的域
- **THEN** 创建被拒并说明该 key 属于一个已归档的域，需先恢复或换 key

### Requirement: 归档与恢复同日可逆

归档 SHALL 只写 `archived_at`，SHALL NOT 改动任何其它列；恢复 SHALL 只清空该列。因此两个动作在任何时刻都可互相回退，且不需要数据修复。

#### Scenario: 反复归档恢复不产生副作用
- **WHEN** 同一域被归档、恢复、再归档
- **THEN** 除 `archived_at` 的取值外，该域行与关联数据完全不变
