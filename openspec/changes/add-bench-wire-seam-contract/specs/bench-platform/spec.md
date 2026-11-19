# bench-platform Specification（delta）

## MODIFIED Requirements

### Requirement: 柏讯实体升格契约

平台 SHALL 从 fd-wire entity-layer 读取实体/关系声明作为 **seed 升格原料**，按 raw→bronze→silver→gold 审核流升格。seed 导入 SHALL 是**一次性**操作：重复导入幂等（零新增行、不 bump 更新时间），但平台 MUST NOT 以定时任务或常驻通道持续镜像 wire 的变化——平台的工作 MUST NOT 因为 wire 停止变化而停止。

**wire 是 seed 原料源，已发布本体的权威源是平台**（蓝图 §六）。平台发布面是全部消费者的唯一权威分发路径；wire 侧本地存储与平台发布版本的分歧按消费者侧本地版本化处理，MUST NOT 形成第二权威。

升格流水线 SHALL 保证：

- seed 阶段 wire 为原料身份的参照键（平台 KU 以 wire 源引用与 `external_key` 回指 seed）；
- 两层之间的语义同一性 SHALL 只经 crosswalk 表达（见 `bench-wire-seam`），MUST NOT 靠复制词表或以 wire 键作为平台主键来「实现对齐」；
- gold 回写 wire 时 SHALL 附带 `sensitivity`/`tier` 标记（面向 seed 源的档位回写，供其 ACL 与舰队消费）；回写方向 SHALL 单向——只承载平台已确认的标注，MUST NOT 承载 wire 实体的结构性变更，且机器草稿 MUST NOT 触发回写；
- 升格与回写全程 SHALL 可追溯（每条 gold 可回指 wire 源声明与审核人）；发布契约见 `knowledge-distribution`。

#### Scenario: 实体升格入库
- **WHEN** 一次性导入 wire 实体声明并经机器预标注（bronze）与人工核验（gold）
- **THEN** 知验台产生带 wire 源引用的 gold 实体，seed 身份可回指 wire；平台发布的本体版本以该 gold 内容为权威形态

#### Scenario: 重复导入幂等但不是持续同步
- **WHEN** 对同一 wire 图谱连续导入两次，随后 wire 一周无变化
- **THEN** 第二次导入零新增行；平台创作、评审与发布流程在该周内照常进行，不报同步停滞

#### Scenario: gold 回写带档
- **WHEN** gold 实体/关系回写 wire
- **THEN** 回写载荷含 sensitivity/tier 标记，wire 侧 ACL 与舰队可直接消费；回写失败如实报错且知验台侧状态不误标「已回写」

#### Scenario: 草稿不触发回写
- **WHEN** 一条单元仍是 bronze（机器预标注）或尚未经人工核验
- **THEN** 不产生任何指向 wire 的写请求

#### Scenario: 发布权威源
- **WHEN** 消费者（含 wire）经分发面拉取平台已发布本体
- **THEN** 快照以平台发布版本为权威（digest 锚定），消费者本地处理不构成第二权威源；wire 本地存储与平台发布版本的分歧按消费者侧本地版本化处理（对账依 pull 面）
