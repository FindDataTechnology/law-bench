## Context

见 `proposal.md` — Why。这里只列塑造方案的既有事实。

- `knowledge_units` 表已有 `kind / namespace / external_key / body / tags / attrs / tier / provenance / source_path / derived_from`（`src/bench/store.py:36-41`），`attrs` 与 `provenance` 都是 JSONB、被子系统当不透明载荷。断言的落点不需要新表。
- 提案箱、证据逐字回源校验、`tier` 守卫、事件流、发布 digest 全部已存在且与 kind 无关（`bench-platform` 的「新增 kind 不改内核」已钉住）。新增一个 kind 的增量成本是**零内核改动**。
- `ontology-authoring` 的关系端点校验是「本域已存在且未软删的实体」（spec 已写），这与 crosswalk 是两套东西——顺带把这条边界写成显式断言，防止后来人拿 crosswalk 去放宽它。
- `fd-erp-vertical-templates/connector-status.json` 已有 8 个 provider 与 `{catalog, executor_tests, live}` 三态结构（每态 `{ok, evidence, accepted_at}`），口径由 `erp-connector-onboarding` 规格钉住。本变更**沿用该口径**，只换存放位置与读面。

## Goals / Non-Goals

**Goals:**

- 一条 crosswalk = 一个 KU 行，零新表、零新机制。
- 三种关系种类构成闭集，方向固定，反向查询派生。
- 三态证据与 crosswalk 在同一读面可查，读面以知验台为权威。
- 「接一个新 ERP 厂商 = 一批 KU 行」这条成本结构在 spec 里成为可验证的断言。

**Non-Goals:**

- 不做自动确认。`confidence ≥ 阈值` 直接过会绕过「机器只能提名」，那是平台最硬的一条规则。
- 不把 ERP 的 `erp-account-mapping/v1` 形状搬进来或反过来改变它。既有 pack.json 形状零改动；映射内容以 KU 行重新表达，两者通过 `maps_to` 关系互相指认，读面标注哪一份是权威。
- 不改 `knowledge_units` 的 schema。若发现需要新列，说明设计错了。
- 不迁既有 `connector-status.json` 的存量内容作为唯一真源——先双写，读面以知验台为准，本地文件降为降级读。

## Decisions

### D1：`kind='crosswalk'` 而不是新表

**为什么**：新表要重新实现提案箱、证据校验、tier 守卫、事件流、发布、审计、权限，七件事全部已存在于 KU 路径上。用一个 kind 就全部白拿，且这些机制未来任何改进自动作用于 crosswalk。

**替代方案（否决）**：`crosswalks` 独立表。理由是「映射有独立生命周期」——但那个生命周期与 KU 的完全同形（提名→确认→复核→发布），独立表的唯一代价是复制七套机制。

### D2：`attrs` 承载对端，`external_key` 承载本端

```json
{
  "kind": "crosswalk",
  "external_key": "customer:acme",
  "attrs": {
    "relation": "same_as",
    "peer": {"kind": "external_id", "system": "salesforce", "id": "0014x0000012345"},
    "confidence": 0.94,
    "connectivity": {
      "catalog":         {"ok": true,  "evidence": "open-connector-mt/catalog/apps/shopify_admin.json", "at": "2026-11-12"},
      "executor_tests":  {"ok": true,  "evidence": "open-connector-mt/src/providers/shopify_admin/*.test.ts (1)", "at": "2026-11-12"},
      "live":            {"ok": false, "evidence": null, "at": null}
    }
  },
  "provenance": {"source": "fleet:erp-onboarding/round-7", "quote": "..."},
  "tier": "bronze"
}
```

**为什么不把 relation / peer 拆成列**：`attrs` 的定位在 `store.py` 里写明是「domain fields the kernel treats as opaque」——crosswalk 正是这样一个 domain。拆列会让内核认识 crosswalk 的形状，违反 pkg 无关性，且下一次要加关系种类就得改表。

**代价**：读面查询得走 JSONB 表达式（`attrs->>'relation'`）。对此的回应是加两个表达式索引（`relation`、`peer->>'system'`），只此两处。

### D3：`role_of` 方向是「角色实体 → 目标实体」

`customer:acme --role_of--> organization:acme-corp`。语义是「acme 这个客户，是 acme-corp 这家机构所扮演的角色」。

**为什么不反过来**（`organization --has_role--> customer`）：正方向让 `external_key` 与 KU 身份规则一致——本端就是那个实体（客户），而客户才是被外部系统记录的那个对象（Salesforce Account 记录的是「这家公司的客户身份」，不是「公司」）。金蝶的客户档案同理。

**代价**：查「这家机构有哪些角色」要走派生（按 `peer` 反查），而不是读一行。

### D4：三态证据挂在 KU 上，读面以知验台为权威

`connectivity` 放在 `attrs` 里。ERP 侧的 `connector-status.json` 保留为生成来源，切换后它是知验台的**镜像**而不是权威。

**为什么**：三态证据与 crosswalk 是同一件事的两面——「这家厂商的记录对应我们的哪个实体」与「这条对接验收到哪一档」问的是同一个外部系统。分两处存就必须有对账，而对账的代码是第一份会 rot 的东西。

**兼容读面**：`GET /api/d/{domain}/crosswalks/connectivity/{system}` 返回与 `connector-status.json` 同形的结构（`integrations[].states.{catalog,executor_tests,live}.{ok,evidence}`），使 ERP 侧生成器可以一行不改地先切过来源，再逐步迁移。

### D5：映射覆盖率按实体计，不按映射行计

分子 = 至少有一条「已复核且未过期」映射的活实体数；分母 = 活实体数。

**为什么**：按行计会让「给一个实体挂 10 条映射」把覆盖率刷到虚高，而质量比存在的全部意义是「不能被灌量糊弄」（`domain-quality-metrics` 的「缺口关闭不等于质量达标」是同一条）。

### D6：两类缺口分列，都不合并

`quality:crosswalk_stale`（证据过期或指向的外部系统已变）与 `quality:crosswalk_unconfirmed`（低置信未复核）。两者路由都到 `fleet`，聚合键为「域 + 外部系统」。

**为什么不合并**：合并后的计数无法区分「你接的那个系统变了（要重验）」与「你的映射还没人看（要用人）」——这是两种完全不同的处置，合并后 operator 只能看到「映射有问题」然后无从下手。

### D7：协议侧只在新增文件里做对齐声明

`fd-open-data-protocol` 增加 `vocabulary/alignment/foundation.yaml`，不改六个既有词表文件、不改 `version` 语义。理由：那六个文件被 golden digest 测试钉死（`tests/golden/`），改任何一个字节都会作废既有发布账。

## Risks / Trade-offs

- [JSONB 查询性能] → 两处表达式索引；读数在域级（每域实体数百到数千），不构成瓶颈。若真成瓶颈，升级路径是物化视图，不改 KU 形状。
- [`attrs` 无结构校验的诱惑] → 校验集中在 `src/bench/crosswalk.py` 一个纯函数（`validate_crosswalk(attrs) -> list[str]`），写入路径与读面共用它；禁止在路由层另写一份校验。
- [ERP 侧切换读面时网络不可达] → 兼容读面与本地文件双读，不可达时**回退本地并在输出里标注 `source: local-fallback`**，不静默使用过期数据。这是 `erp-connector-onboarding` 的既有纪律（未接通必须如实 501，不许假实现）。
- [三态证据的「过期」阈值各域不同] → 阈值进模板的 `corpus_declaration` 同级配置位（域级），不由内核定死；未配置时**默认不过期**并注明「未设有效期」，不默认一个数字。
- [跨三仓验收易变成单侧自证] → 验收判据固定为「同一厂商、同一实体，知验台与 ERP 各查一次，输出逐字段一致」，两侧各跑一次并比对；单侧期望值不算证据。

## Migration Plan

1. `kind='crosswalk'` 上线（读面 + 校验 + 提案路径）。存量零迁移。
2. ERP 兼容读面上线，`connector-status.json` 生成器切到读知验台（不可达时回退本地并标注）。
3. 把既有 8 个 provider 的三态证据导入为 crosswalk 行的 `connectivity`（一次性脚本，幂等）。
4. 把 `references/collateral` 之外的既有 `account-mapping` 内容以 `maps_to` 关系表达一份（**不删旧文件**，只在读面标注权威）。
5. 回滚：读面路由下线 → ERP 生成器切回本地文件；KU 行保留（不破坏事件流）。

## Open Questions

- 「外部系统已变」的判定口径（字段消失、类型变化、样本为空）要不要进 spec？当前只落到「证据过期」这一条可机械判定的口径；更细的 drift 检测留给后续，不阻塞本变更。
