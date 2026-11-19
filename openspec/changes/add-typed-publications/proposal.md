## Why

`docs/knowledge-platform-blueprint.md` §六 写下的是「本体 / RAG 语料 / 金集三类均可发布，digest + changelog」。**代码只做了第一类**：`src/bench/distribution.py` 的 `publish_domain()` 只从模板词表里取实体与关系单元，`ontology_publications` 的 manifest 形状是本体专用的（`entity_types` / `relationship_kinds` 锚定）。尺子（rubric）与金集（sample）到今天为止只能被「挂到某个域的书架上」（`domain_assets` 的目录语义），不能被**发布成一个带 digest 的不可变版本**。

后果是具体的：壹座舰队现在有 `add-bench-ops-tools` 提供的回写能力，但**它拿到的是运行台账，不是评分标准**。舰队想按知验台的尺子自评，只能读到「当前生效的 rubric」，而「当前生效」是一个会变的视图——同一个舰队昨天与今天评出的分数不可比，也正是蓝图 §五 那条 `meta-eval` 漂移链想要消掉的东西。发布之所以必要，不是因为要「管起来」，而是因为**只有不可变快照才能让两次评测可比**。

为什么现在做：`add-fleet-execution-loop` 让舰队成为可登记、可回写的执行方；尺子一发出去，舰队就能在本地按同一把尺子评、并把结果连同 digest 一起回写。再往后拖，先上产的那批舰队会先长出一套自己的口径。

## What Changes

- **发布种类由 pack 注册，内核不认识任何行业**——沿 `domain_assets.register_providers` 的既有做法：一个 pack 为每类资产登记一个「条目投影」，内核只负责版本、digest、不可变性、变更日志与拉取面。新增 `rubric` 与 `sample`（金集）两类；本体继续走既有的 `ontology_publications` 与既有拉取契约，**不迁移、不改 digest 配方**。
- **digest 只有一份实现**：新种类的条目投影交给既有的规范序列化内核（键序归一、排除生成时间戳），MUST NOT 各自写一份 digest 逻辑——两份实现对「同一内容」判定不一致时，跨面比对就失去意义。
- **按种类的机器拉取面**：`GET /api/v1/distribution/{domain_key}/{kind}`，沿用既有三态鉴权（401 / 403 未登记 / 403 越域）与 `X-Consumer-Token` 纪律；`kind` 只接受已注册的种类，未注册的如实报错而不是 404。
- **发布页与台账列三类**：域控制台的发布区显示本体、尺子、金集各自的版本与 digest；缺数据的种类显示自己的空态，不合并计数。
- **非目标**：不迁移既有本体发布（wire 在生产拉取，重算 digest 会作废它）；不做跨域合并发布；不做第三类之外的「任意资产可发布」泛化——先只做蓝图已承诺的两类。

## Capabilities

### New Capabilities

- `asset-publication`: 非本体资产的发布契约——种类由 pack 注册、条目投影与共享 digest 内核、不可变版本与变更日志、按种类的拉取面与鉴权三态，以及「发布不等于归属」的边界（发布不改变资产的归属目录语义）。

## Impact

- **代码（law-bench-internal）**：
  - `src/bench/publication_kinds.py`（新）：种类注册表 + 条目投影契约（与 `domain_assets` 的 provider 契约同形）。
  - `src/bench/distribution.py`：新增 `publish_asset_kind()` / `get_asset_publication()` / `list_asset_publications()`，digest 复用 `canonical_digest()`；既有 `publish_domain()` 零改动。
  - `src/bench/workspace_store.py`：新增 `asset_publications`（`domain_id`, `asset_kind`, `version`, `digest`, `manifest`, `changelog`, `published_by`, `published_at`，唯一 `(domain_id, asset_kind, version)` 与 `(domain_id, asset_kind, digest)`）与拉取足迹表。
  - `src/web/routes/distribution.py`：按种类的拉取路由。
  - `packs/*/asset_catalog.py`：为 `rubric`、`sample` 各声明发布投影（哪些列进 manifest、排序键）。
- **契约**：`docs/domain-proposal-contract.md` 不涉及；新增 `docs/asset-publication-contract.md` 说明种类注册与 pull 载荷。
- **依赖**：`add-fleet-execution-loop` 的消费者登记（`kind='fleet'`）——舰队既是执行方也是尺子的消费者。
- **风险**：新增拉取面扩大了对外攻击面。缓解：种类白名单（未注册即拒）、沿用既有 token 校验、发布只读、拉取足迹只增。

## 明确不做的一件事

不把 `ontology_publications` 改名为 `asset_publications` 并回填本体行。理由：wire 正在生产上按 `GET /api/v1/distribution/{domain}/ontology` 拉取，digest `5897354d` 已被消费方持有；重算或搬表会让已发布版本的 digest 失效，而 digest 的唯一用途就是「可核对」。本体与尺子共存的代价只是多一张表，收益是**已经发出去的账不被作废**。
