## Purpose

两层本体之间的缝：一条 crosswalk 就是一个可确认、可复核、可发布的知识单元，声明「本层某端点」与「对层某端点或某外部系统标识符」之间的关系（同一实体 / 角色 / 值域映射）。它让「接一个新 ERP 厂商」成为一批 KU 行而不是一个新模板，并让映射的置信度、证据与三态验收一起可查。

## ADDED Requirements

### Requirement: crosswalk 是以知识单元承载的映射断言

一条 crosswalk SHALL 是一个知识单元（`kind='crosswalk'`），其身份 SHALL 由「作用域 + `external_key`」确定，与既有知识单元同一套身份规则。它 MUST NOT 使用独立的数据表，MUST NOT 有绕过唯一写路径的写入方式。

`external_key` SHALL 取本层端点的规范键（`<实体类型>:<类型内键>`），SHALL 是语义键而非自增编号。

写入 SHALL 经内核唯一写路径（词表校验 + 追加式事件），每次写入 SHALL 只追加一条事件。

#### Scenario: 一条 crosswalk 落为一个 KU 行
- **WHEN** 提交一条本层端点 `customer:acme` 指向外部标识符 `salesforce:0014x0000012345` 的映射并被确认
- **THEN** `knowledge_units` 中出现一行 `kind='crosswalk'`、`external_key='customer:acme'`，并追加一条 created 事件

#### Scenario: 不存在独立表
- **WHEN** 检视 schema，寻找 crosswalk 专用表
- **THEN** 不存在这样的表；映射数据只存在于知识单元行中

### Requirement: 关系种类是闭集且方向固定

crosswalk 的关系种类 SHALL 取以下闭集之一：`same_as`（同层异系统或跨层的同一实体）、`role_of`（本端点是目标实体的一个角色）、`maps_to`（值域映射，如行业科目对齐通用科目）。提交闭集外的种类 SHALL 被拒绝并列出闭集成员。

关系方向 SHALL 固定为「本层端点 → 对端」。反向查询 SHALL 由读面派生，MUST NOT 另存一条反向行——同一个事实存两条会在两侧更新不同步时互相矛盾。

#### Scenario: 未知关系种类被拒
- **WHEN** 提交 `relation: "equivalent"` 的 crosswalk
- **THEN** 写入被拒绝并列出三种合法关系种类

#### Scenario: 反向查询由派生实现
- **WHEN** 以 `salesforce:0014x…` 为参数查询「谁映射到我」
- **THEN** 返回 `customer:acme`，且库中不存在一条反向的 KU 行

### Requirement: 对端支持外部标识符与跨层本体键两种形态

crosswalk 的对端 SHALL 为以下两种形态之一：

- `external_id`：外部系统的标识符，携带 `system`（如 `salesforce` / `kingdee`）与 `id`；
- `ontology`：另一层本体的端点，携带 `layer_ref`（该层模板的标识）与 `<类型>:<键>` 形式的端点。

对端形态不在上述两者内、或缺少必需字段时 SHALL 被拒绝并点名缺哪一项。

#### Scenario: 外部标识符形态
- **WHEN** 提交对端 `{kind: "external_id", system: "kingdee", id: "BD001"}`
- **THEN** 写入被接受

#### Scenario: 跨层本体形态
- **WHEN** 提交对端 `{kind: "ontology", layer_ref: "external-world-2026.11", endpoint: "company:acme-corp"}`
- **THEN** 写入被接受

#### Scenario: 缺 system 被拒
- **WHEN** 提交对端 `{kind: "external_id", id: "BD001"}`（缺 `system`）
- **THEN** 写入被拒绝并指明缺 `system`

### Requirement: 映射走提案→确认，机器只能提名

由机器或智能体产生的 crosswalk 候选 SHALL 全部写成待确认提案，MUST NOT 直接进入本体。确认 SHALL 逐条经唯一写路径落地，单条失败 SHALL NOT 回滚其余。

提案 SHALL 携带来源标识与原文片段作为证据；证据 SHALL 被逐字回源校验（允许空白归一），找不到即判定无效并计入拒绝原因。

撰写者 MUST NOT 确认自己的提案。

#### Scenario: 机器提名不进本体
- **WHEN** 舰队提交 20 条 crosswalk 候选
- **THEN** 待确认提案增加 20 条，本体中的 crosswalk 数量不变

#### Scenario: 编造的字段证据被丢弃
- **WHEN** 候选声称某外部系统的字段名为 `cust_name` 而该系统的样本中不存在该字段
- **THEN** 候选被丢弃并计入「证据不成立」，不进入复核队列

#### Scenario: 自提自确认被拒
- **WHEN** 提交者试图确认自己提交的 crosswalk
- **THEN** 确认被拒绝并说明须由他人确认

### Requirement: 低置信映射必须挂起待复核

confidence 低于该域声明阈值的 crosswalk SHALL 在确认后仍处于「待复核」状态，SHALL NOT 被当作已确认映射用于覆盖率统计或对外声明。读面 SHALL 明确标出该状态，MUST NOT 与已复核映射合并计数。

confidence 缺失 SHALL 视为低于任何阈值（fail closed），MUST NOT 视为「无置信度要求」。

#### Scenario: 低置信挂起
- **WHEN** 一条 confidence=0.4 的 crosswalk 被确认且域阈值为 0.8
- **THEN** 该映射状态为「待复核」，不计入映射覆盖率

#### Scenario: 缺 confidence 按低置信处理
- **WHEN** 提交的 crosswalk 未带 confidence
- **THEN** 其状态为「待复核」而不是「已确认」

### Requirement: 外部系统接通状态以三态证据判定

每条指向外部系统的 crosswalk SHALL 可携带三态证据：`catalog`（连接器目录有该 provider）、`executor_tests`（执行器有测试）、`live`（live 验收凭证）。每态 SHALL 携带证据引用（路径、测试名或验收记录标识）与时间。

只有三态全部到位，该外部系统才可对外声明「已接通」。任一态缺失 SHALL 报「未接通」并点名缺失态，MUST NOT 以「其余两态已通过」推断接通。

证据过期（超过该域声明的有效期）SHALL 使该态退回缺失，并在读面标出过期而非删除记录。

#### Scenario: 缺 live 报未接通
- **WHEN** 金蝶的 catalog 与 executor_tests 均到位而无 live 验收记录
- **THEN** 读面报「未接通（缺 live）」，不得声明已接通

#### Scenario: 证据过期退回缺失
- **WHEN** 某 provider 的 live 验收记录超过有效期
- **THEN** live 态退回缺失并标注过期，其余两态不受影响

#### Scenario: 三态齐备才声明接通
- **WHEN** 某外部系统三态证据全部到位且未过期
- **THEN** 读面可声明「已接通」，并列出三份证据引用

### Requirement: 映射断言不构成关系图谱的边

crosswalk SHALL NOT 被当作本体关系参与图谱遍历、端点闭合校验或关系参照完整率统计。它是一层薄映射，不是本体内部的边。

在读面上，以实体为起点查「它的关系」与查「它的映射」SHALL 是两个不同的查询，MUST NOT 合并成一个结果集。

#### Scenario: 图谱遍历不含 crosswalk
- **WHEN** 从 `customer:acme` 出发做关系遍历
- **THEN** 结果不包含任何 crosswalk 对端，即便它们指向同一实体

#### Scenario: 两个查询分开
- **WHEN** 分别查询某实体的关系与映射
- **THEN** 两个查询的返回结构不同，且映射查询结果标出关系种类、对端形态与复核状态

### Requirement: 映射过期与未复核是独立缺口

「已确认映射指向的外部系统已变或证据过期」与「低置信映射未复核」SHALL 作为两类独立缺口报出，MUST NOT 合并为「映射有问题」一个计数。两类缺口 SHALL 可被派单，目标为舰队（需要判断），聚合键为「域 + 外部系统」。

同一域同一外部系统的同一缺口已存在未关闭工单时，再次派单 SHALL 报「已指派」并给出既有工单标识。

#### Scenario: 过期缺口独立报出
- **WHEN** 某域有 3 条映射的外部系统证据过期
- **THEN** 报「映射过期」缺口 3 条，与「未复核」缺口分别计数

#### Scenario: 重复派单收敛
- **WHEN** 对同一域同一外部系统的过期缺口再次派单
- **THEN** 报「已指派」，不新建工单

### Requirement: 映射覆盖率可从库里反算

质量视图 SHALL 提供「映射覆盖率」：本域实体中至少有一条**已复核且未过期** crosswalk 的比例，并给出分子、分母与算法说明。

覆盖率 SHALL NOT 因映射总数增长而虚高：同一实体挂 10 条映射与挂 1 条，对该实体的覆盖率贡献相同。

#### Scenario: 按实体而非按映射计数
- **WHEN** 某域 10 个实体，其中 4 个各挂若干映射
- **THEN** 覆盖率显示 4/10，说明分母是活实体数而不是映射行数

#### Scenario: 未复核不计入分子
- **WHEN** 某实体的唯一映射处于待复核状态
- **THEN** 该实体不计入分子，覆盖率如实低于 100%
