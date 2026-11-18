# bench-platform Specification（delta）

## Purpose

权威源翻转落地：总纲（`docs/knowledge-platform-blueprint.md` §六）裁定「已发布本体的权威源是平台，wire 是 seed 原料源与拉取方」。修订「柏讯实体升格契约」需求使 spec 与总纲一致；升格-回写环作为 seed 喂入+质量闸的语义完整保留。

## MODIFIED Requirements

### Requirement: 柏讯实体升格契约

平台 SHALL 从 fd-wire entity-layer 读取实体/关系声明作为 **seed 升格原料**，按 raw→bronze→silver→gold 审核流升格；升格流水线 SHALL 保证：seed 阶段 wire 为原料身份的参照键（平台 KU 以 wire 源引用与 `external_key` 回指 seed），**已发布本体的权威源是平台**（平台经版本化发布面向全部消费者分发，wire 作为消费者拉取快照落本地自行处理）；gold 回写 wire 时 SHALL 附带 `sensitivity`/`tier` 标记（面向 seed 源的档位回写，供其 ACL 与舰队消费）；升格与回写全程 SHALL 可追溯（每条 gold 可回指 wire 源声明与审核人）；发布契约见 `knowledge-distribution`。

#### Scenario: 实体升格入库
- **WHEN** 同步 wire 实体声明并经机器预标注（bronze）与人工核验（gold）
- **THEN** 知验台产生带 wire 源引用的 gold 实体，seed 身份可回指 wire；平台发布的本体版本以该 gold 内容为权威形态

#### Scenario: gold 回写带档
- **WHEN** gold 实体/关系回写 wire
- **THEN** 回写载荷含 sensitivity/tier 标记，wire 侧 ACL 与舰队可直接消费；回写失败如实报错且知验台侧状态不误标「已回写」

#### Scenario: 发布权威源
- **WHEN** 消费者（含 wire）经分发面拉取平台已发布本体
- **THEN** 快照以平台发布版本为权威（digest 锚定），消费者本地处理不构成第二权威源；wire 本地存储与平台发布版本的分歧按消费者侧本地版本化处理（对账依 pull 面）
