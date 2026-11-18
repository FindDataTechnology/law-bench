# domain-proposal-inbox Specification（delta）

## Purpose

域提案箱：把「生产出来的草案」落在它所属的域里等人确认。自动岗与专家都是提交方，负责人是唯一的确认方；确认后仍走内核唯一写路径落库。这是蓝图铁律一「平台自成闭环」在人面上的形态——生产在平台内闭环，消费者只消费已发布版本。

## ADDED Requirements

### Requirement: 草案入箱且携带可核对依据

任何草案（自动岗或人工）SHALL 先进入所属域的提案箱，初始状态为 `pending`。一条提案 SHALL 携带：来源（岗位身份行或人工身份）、目标 kind、`external_key`、正文、依据（来源数据集/列/列级证据或引用的知识单元）、影响说明、提交时间。提交 SHALL NOT 直接写入知识单元。

提案 SHALL 在域边界内：提案的域由提交目标显式给定，且提交方 SHALL 在该域持有可提交的域角色；跨域提交 SHALL 被拒绝。

#### Scenario: 自动岗草案进入域箱

- **WHEN** 舰队提案岗向域 D 提交一条实体草案
- **THEN** 域 D 的提案箱出现一条 pending 提案，携带岗位身份行、kind、external_key、正文与依据，知识单元库无新增

#### Scenario: 缺依据的提案被拒

- **WHEN** 提交的提案不携带任何依据字段
- **THEN** 提交被拒绝并报明「提案必须携带依据」，不产生任何提案行

#### Scenario: 跨域提交被拒

- **WHEN** 一个只在域 A 有成员身份的主体向域 B 提交提案
- **THEN** 提交被拒绝（fail-closed），域 B 的提案箱与知识单元均无变化

### Requirement: 确认即经内核收口落库

`lead`/`admin` 确认提案时，系统 SHALL 经内核唯一写路径（`upsert_knowledge_unit`）落库：kind 词表执法、域 namespace 隔离、变更事件与内容同事务。确认后提案状态 SHALL 变为 `confirmed`，并记录确认人与确认时间。同 `external_key` 已存在时 SHALL 按更新语义处理，并产生 `update` 事件而非静默覆盖。

确认动作 SHALL NOT 存在第二条写路径（不经提案箱直接写库的人工入口仍走既有创作面，二者共用同一内核函数）。

#### Scenario: 确认后实体可查且留痕

- **WHEN** 负责人确认一条实体提案
- **THEN** 该实体以域 namespace 落库并可被检索，提案状态为 confirmed 且记录确认人与时间，事件流出现对应 create/update 事件

#### Scenario: 出表 kind 在确认时被拦

- **WHEN** 一条 pending 提案的 kind 不在该域当前模板词表内（例如提交后模板被降版本）
- **THEN** 确认被拒绝并报明词表约束，提案保持 pending，知识单元库无变化

#### Scenario: 重复确认幂等

- **WHEN** 同一提案被确认两次
- **THEN** 第二次不产生第二条知识单元、不产生第二个确认事件，提案状态保持 confirmed

### Requirement: 驳回退回且同键不自动重提

驳回 SHALL 把提案置为 `rejected` 并记录驳回理由与操作者；被驳回的提案 SHALL NOT 被自动重提。同一来源针对同一 `external_key` 在驳回后再次提交时，仅当携带**新的依据版本**（依据摘要不同）时才 SHALL 被接受；否则 SHALL 被拒绝并提示「同键已驳回，需新证据」。

同一域内，同一来源、同一 `external_key`、同一状态为 `pending` 的提案 SHALL 幂等去重：重复提交 SHALL NOT 产生第二条 pending 行，SHALL 返回既有提案。

#### Scenario: 无新证据的重复提交被拒

- **WHEN** 某来源的草案被驳回后，同日以完全相同的依据再次提交
- **THEN** 提交被拒绝并提示需新证据，提案箱不新增 pending 行

#### Scenario: 新证据允许重提

- **WHEN** 同一来源对同一 external_key 携带与上次不同的依据摘要再次提交
- **THEN** 提交被接受，提案箱出现新的 pending 行（历史的 rejected 行保留可查）

#### Scenario: 重复提交幂等

- **WHEN** 同一来源对同一 external_key 在 pending 未决时重复提交三次
- **THEN** 提案箱只有一条 pending 行，三次提交返回同一提案标识

### Requirement: 提案箱的角色权限

提案箱的角色边界 SHALL 为：`expert` 可提交并查看本域提案箱；`lead`/`admin` 可确认与驳回；`annotator` 只读查看本域提案箱；非成员 SHALL 被拒绝且零暴露。提交方与确认方 SHALL 可以不同人，但 SHALL NOT 允许同一身份自提自确认（`admin` 平台身份例外，须留痕标明）。

#### Scenario: 专家不能自提自确认

- **WHEN** 一个 `expert` 提交提案后尝试确认它
- **THEN** 确认被拒绝（403），提案保持 pending

#### Scenario: 只读角色看不到确认入口

- **WHEN** 一个 `annotator` 打开本域提案箱
- **THEN** 看得到提案列表与状态，看不到确认/驳回按钮，直接调用确认接口返回 403

### Requirement: 待确认计数与总览一致

域总览 SHALL 呈现提案箱的待确认计数，该计数 SHALL 与提案箱实际 pending 行数一致（同一次读取口径），`expert` 及以上角色可见。无 pending 时 SHALL 显示 0 而非隐藏该指标。

#### Scenario: 计数与实际一致

- **WHEN** 提案箱有 3 条 pending
- **THEN** 域总览显示 3，进入提案箱可数出同样 3 条

#### Scenario: 清零后显示零

- **WHEN** 全部 pending 被确认或驳回
- **THEN** 域总览显示 0，不隐藏计数

### Requirement: 提案箱是生产闭环的平台侧落点

提案箱 SHALL 是本平台内自动岗草案的唯一落点；本能力 SHALL NOT 依赖消费者系统（柏讯）的审批队列完成确认。提案箱的状态变更 SHALL 全部留痕（提交、确认、驳回各自记录操作者与时间），且历史状态 SHALL NOT 被改写或删除。

#### Scenario: 生产确认不经过消费者

- **WHEN** 一条自动岗提案被域负责人确认
- **THEN** 落库在平台域内完成，消费者系统不参与该确认动作

#### Scenario: 状态历史不可改写

- **WHEN** 检查提案的状态变更记录
- **THEN** 每次状态变更都有一条带操作者与时间的记录，历史记录不可更新或删除
