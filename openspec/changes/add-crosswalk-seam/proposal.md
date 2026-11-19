## Why

分层之后（`add-layered-ontology-templates`），两层本体之间必须有一条可查的缝，否则「同一个客户在 Salesforce、金蝶、知验台三处是同一个实体」这句话无法被任何系统验证。

今天这条缝的三段分别活在三个地方，且互不相认：

- **跨层对齐**：`fd-open-data-protocol` 的 `concept-crosswalk` 与 `external-entity-anchors` 两条 spec 定义了 Variable↔外部词表、实体↔Wikidata/DCID 的映射（带 relation / confidence / provenance / review state），知验台的 `src/bench/` 里**一行都没有**；
- **行业映射**：ERP 的 `account-mapping`（`X-0001 平台销售收入 → 4000`）本质就是一次 crosswalk，但它长在 `fd-erp-vertical-templates` 的模板资产里，形状是 `erp-account-mapping/v1`；
- **外部系统接入**：`fd-erp-vertical-templates/connector-status.json` 已有 8 个 provider（kingdee / shopify_admin / cn-commerce / wechatpay / wms / pos / carrier-portal / supplier-portal）的三态证据（catalog / executor_tests / live），但三态是 ERP 自己的口径，知验台读不到。

后果：接一个新 ERP 厂商时，没有一处能回答「这家厂商的客户档案对应本体里的哪个实体、映射置信度多少、谁确认的、这个对接的验收证据到哪一档」。而这三问的答案是「持续自迭代」的成本曲线能否撑住的关键——模板数应该等于行业数（个位数不动），映射数才等于厂商数（会长）。

为什么现在做：分层刚落，缝不上去，两层就只是两份并列的词表，`aligned_with` 声明无处落地。

## What Changes

- **crosswalk 作为一种知识单元**：新增 `kind='crosswalk'`，一条 crosswalk 就是一个 KU 行（`external_key` 为本层端点，`attrs` 承载对端端点与关系类型，`provenance` 承载证据，`tier` 承载可信档位）。**零新表**——白拿提案箱、证据逐字校验、人确认、tier 守卫、事件流、发布 digest。
- **三种关系种类构成闭集**：`same_as`（同层异系统同一实体）、`role_of`（角色关系，如 `customer` 是 `organization` 的角色）、`maps_to`（值域/科目映射）。关系方向固定，反向查询由读面派生而非另存一行。
- **外部系统标识符作为端点**：`attrs.peer` 支持两种形态——`kind: "external_id"`（外部系统标识符，如 `salesforce:0014x…` / `kingdee:BD001`）与 `kind: "ontology"`（另一层的本体键，如 `observation:company:acme-corp`）。
- **三态证据挂到 crosswalk 上**：`catalog` / `executor_tests` / `live` 三档，每档带证据路径与时间。三档全到位才可对外声明「已接通」，任一缺即「未接通（缺 X）」——口径沿用 `erp-connector-onboarding` 的既有三态判定，不重写。
- **新增两类缺口进入派单路由**：`quality:crosswalk_stale`（映射指向的外部系统已变或证据过期）与 `quality:crosswalk_unconfirmed`（低置信未复核），均路由到舰队。
- **`fd-open-data-protocol` 侧加一条对齐声明**：观测层模板与 `foundation` 的 `aligned_with`（`company → organization`、`city → place` 等），一条声明替代 N 条逐项 crosswalk。协议仓只加声明文件，不改词表、不改 digest。

## Capabilities

### New Capabilities

- `crosswalk-seam`: crosswalk 作为知识单元的身份与形状、三种关系种类的闭集与方向语义、外部标识符与跨层端点两种形态、提案→确认→复核生命周期、低置信挂起，以及「接一个新外部系统 = 一批 KU 行，不是一个新模板」这条成本约束。

### Modified Capabilities

- `ontology-authoring`：明确 crosswalk **不是关系**、不参与本体关系图谱遍历与端点闭合校验；关系的两端口径不变。
- `domain-quality-metrics`：新增「映射覆盖率」为独立质量比（本域实体中至少有一条已确认 crosswalk 的比例）。

> `bench-platform` 无需改规格：其「新增 kind 不改内核」已覆盖 `kind='crosswalk'` 的接入（既有 kind 列表是举例而非闭集），本变更只在测试一侧加一条断言，不产生 delta。
> `erp-connector-onboarding` 的 delta 在**工作区根** `openspec/specs/erp-connector-onboarding/`（ERP 无自己的 openspec 根），不在本仓 change 内；其要点为：三态证据的存放位置扩展为「也可存放在知验台的 crosswalk KU 上」，两处并存时以知验台为读面权威、ERP 资产为写面来源；**BREAKING** 是该文件既有直接消费者需改读知验台读面（本变更提供兼容读面）。

## Impact

- **代码（law-bench-internal）**：
  - `src/bench/crosswalk.py`（新）：三种关系种类的闭集、端点形状校验、方向派生、三态证据校验。
  - `src/bench/proposals.py`：`kind='crosswalk'` 的提交路径与端点闭合校验（端点不存在 → 拒绝，沿用 `endpoint_open` 口径）。
  - `src/bench/team_roles.py`：质检员增加 `crosswalk_peer_missing` 检查项。
  - `src/bench/estate.py`：第八项质量比。
  - `src/bench/dispatch.py`：两个新缺口的路由。
  - `src/web/routes/`：crosswalk 的读面（按实体查映射、按外部系统查映射、按置信度过滤）。
- **代码（fd-open-data-protocol）**：新增 `vocabulary/alignment/foundation.yaml`（对齐声明，不改既有词表文件），以及一条读取该声明的入口。**不改版本号语义、不改 golden digest 的六个既有文件**。
- **代码（fd-erp-vertical-templates）**：`connector-status.json` 的生成器改为「先读知验台读面，不可达时回退本地」，回退时在读面标注数据来源，MUST NOT 静默使用过期本地文件。
- **契约/文档**：`docs/crosswalk-contract.md`（新）。
- **风险**：跨三个仓，必须两侧同片验收；单侧期望值是自己写的，等于伪证。验收以「同一厂商、同一实体，两侧各自查一次，结果逐字段一致」为准。
- **明确不做**：不做自动确认（`confidence ≥ 阈值` 直接过）。「机器只能提名、人确认才进本体」是平台最硬的一条规则，本变更不改它；量大的问题由「按族定档」在跑满三个月后再裁决，届时别名与证据都在。

## Migration Plan

- `kind='crosswalk'` 是新增 kind，既有 KU 行零迁移。
- ERP 侧 `connector-status.json` 的兼容读面先上线，再切换生成器；切换后保留本地文件作为降级读，读面标注来源。
- 回滚：删除新增 KU 行与新增读面路由；ERP 生成器切回读本地文件。
