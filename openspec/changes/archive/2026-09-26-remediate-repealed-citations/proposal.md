# Proposal: remediate-repealed-citations

## Why

引法审计终局显示：248 条条款（3.5%，tagged 243 / base 5）携带 298 处已废止/失效法律引用，其中 247 处引《合同法》（2021 年被民法典承继）。这些条款组装出的合同会带着死法条出厂。96% 的引用存在明确承继关系（民法典承继六法、建工解释合并、网络交易办法更替），可确定性修复；且修复原因可全部落成**机器可验证的证据链**（死法 law_id → 废止依据 → 承继法 law_id）。修复记录本身是三类下游工作的原料：论文的语料质量前后对照统计、人工复核流、微调修正数据对。

## What Changes

- `law_catalog` schema 新增**承继映射表**（死法 → 承继法，含废止依据 law_id 引用与生效日期；地方废规留待人工占位）与**修订记录表**（clause_id × batch，before/after 引用串、三段 law_id 证据链、规则版本、幂等去重）。
- 修复驱动脚本（沿用 content-remediation 的 batch/dry-run/快照惯例）：审计查询 → 承继映射 → **dry-run 出 diff+原因清单**（人工过目闸门）→ 逐条经 **`update_clause()`** 应用（唯一写路径；law_refs 自动重派生；`manual=true` 副作用=防重新抽取覆盖，已确认接受）→ 重跑 resolve+audit 闭环验证（目标：已废 298 → ≈7）。
- 每批次落 `output/remediation/<batch>/` 快照（manifest 含 git sha + before/applied 整行），支持整批/逐条回滚；**绝不 DELETE**。
- "已修改"17 处以 `reviewed-no-action` 类别留档（法律仍有效仅被修正，不改条款）。
- 记录消费面：论文统计 SQL/导出（前后对照、按类型/原因聚合）；web 修订列表页（before/after diff + 证据链，挂 `/law-catalog/` 路由族）；微调修正对导出（before→after 指令对，对齐既有 finetune-data 约定）。

## Capabilities

### New Capabilities

- `law-citation-remediation`: 废止引法的确定性修复——承继映射、dry-run 闸门、经正规接口应用、带证据链的修订记录（表+快照双面）、回滚、闭环验证与三类消费导出。

### Modified Capabilities

（无——`law-catalog`、`law-citation-audit` 的既有规格行为不变；修复是消费审计结果的新能力。）

## Impact

- **代码**：`src/law_catalog/` 新增 remediation 模块（映射/记录 store、dry-run、apply、rollback、导出）；web 新增修订列表路由+模板；CLI 驱动脚本一个。
- **数据库**：`law_catalog` schema 增两张表（successor_map、citation_revisions），随现有迁移模式走。
- **数据**：248 条条款 body 经 `update_clause` 修改（manual 置位）；`output/remediation/` 快照目录；不删任何行。
- **依赖**：无新增外部依赖；纯确定性替换（不依赖 LLM/网关），隧道即可执行。
- **风险**：误替换历史叙述（如"合同法实施以来"）由 dry-run 白名单+人工过目闸门拦截；before 快照逐条可回滚。
