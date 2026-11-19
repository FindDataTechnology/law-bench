## Context

见 `proposal.md` — Why。设计相关的现状：

- `ontology_publications` 是**生产载荷**：`src/bench/distribution.py` 的 `_PUBLICATION_COLS` 与 `publish_domain()` 都围着它写，wire 在生产上按 `GET /api/v1/distribution/{domain}/ontology` 拉取，digest `5897354d` 已被消费方持有。
- `canonical_digest()`（`src/bench/distribution.py`）是**唯一**的规范序列化内核：键序归一、排除生成时间戳；既有 spec 明确要求「规范形态与 digest 配方 SHALL 由共享内核持有，本面 MUST NOT 再有一份自己的实现」。
- 尺子存在 `rubrics` 表里（`src/eval/rubric_crud.py` 的 legacy CRUD，`domain_id` 可为空），域感知的解析在 `src/bench/domain_rubrics.py`：`effective_rubrics(domain_path)` 沿父链继承，`fork` 必须带 `fork_diff`，`derived_from` 记录血缘。
- 资产种类由 pack 注册：`src/bench/domain_assets.py` 的 `register_providers()` 收「自包含 SELECT + `label_key`」，内核不认识任何行业；`packs/legal/asset_catalog.py` 里已有 `rubric` / `prompt` / `compare` / `sample` / `clause` / `law_info` 六种。

## Goals / Non-Goals

**Goals**
- 尺子与金集能被发布成带 digest 的不可变版本，且**同一份内容在两种入口算出同一 digest**。
- 新增种类只需改 pack，内核零改动（沿用资产目录的 provider 契约）。
- 本体契约零回归：既有路由、载荷字段集、digest 计算逐字节不变。

**Non-Goals**
- 不统一表结构（见 D1）。
- 不发布 RAG 语料（体积与生命周期都不同，另立）。
- 不做跨域合并发布。

## Decisions

### D1 两表并存，不迁移本体发布

新增 `asset_publications`（`domain_id`, `asset_kind`, `version`, `digest`, `shape_version`, `manifest`, `changelog`, `published_by`, `published_at`）只承载非本体种类；`ontology_publications` 一行不动。

**为什么不合并**：digest 的唯一用途是「可核对」，而 `5897354d` 已经在消费方手里，wire 也在按版本号拉。把本体行搬进新表、按新投影重算 digest，等于**作废一条已上产的分发链**——那不是重构，是撤账。多一张表的代价远小于此。

**为什么不复用 `ontology_publications` 加一个 `kind` 列**：它的 manifest 形状是本体会专用的（`entity_types` / `relationship_kinds` 锚定），塞进尺子会让同一列承载两种 schema，读侧每次都要先判形状；而形状判断写在读侧，就是两套实现的开始。

### D2 种类注册沿用资产目录的 provider 契约，不发明第二套

新模块 `src/bench/publication_kinds.py` 的登记项与 `domain_assets` 的 provider 同形：`relation`（自包含 SELECT，一 key 一行）、`label_key`、再加两项发布专用字段 `sort_key` 与 `shape_version`。

**为什么不把投影写进 distribution.py**：内核纯度是本仓既有约束（`domain_assets` 的注释明写「内核给机制，域给参数」）。把 `rubric` 的 SQL 写进 `distribution.py`，第二条垂直线就得改内核。

**替代方案**：直接在 pack 里写 Python 函数供 `publish_asset_kind` 调用 —— 否决，pack 是配置面不是代码面，函数引用会让 pack 加载期执行任意代码。

### D3 digest 复用 `canonical_digest()`，投影只负责「产出条目」

`publish_asset_kind` 把投影结果整理成与该内核同形的条目（按键寻址、键集固定、排序固定），再交给 `canonical_digest()`。**MUST NOT 为新种类写第二份 digest**——两份实现对「同一内容」判定不一致时，跨面比对就失去意义。

`shape_version` 放在载荷之外、不参与 digest（沿既有本体发布的同一条规则）。

### D4 拉取路由：`kind` 段显式白名单，且不遮蔽既有 ontology 路由

`GET /api/v1/distribution/{domain_key}/{kind}` 与既有的 `/ontology` 是同一路径形状。处理方式：

1. 既有 `.../ontology` 路由**保持先注册**，行为不变（它就是 ontology 种类的一条特例路径）；
2. 新路由只接受注册表里的种类，`ontology` 在其中映射回既有 handler；
3. 未注册的 `kind` 返回 400 并列出已注册种类，**不是 404**——404 会让调用方以为路径写错了。

**替代方案**：`/distribution/{domain}/{kind}/{version}` 全统一重写 —— 否决，会改动 wire 正在用的路径语义（版本是 query 参数，不是路径段）。

### D5 尺子的条目键用 `asset_key`，并把血缘投影进去

尺子的稳定标识是 `domain_assets.asset_key`（目录语义里它自己的 key），不是自增 `id`——`id` 在不同域/不同库里不保证同值，用它会让「同一把尺子」在两个域发布出两个 digest。

投影 SHALL 带上 `derived_from` 与 `fork_diff`：消费方必须能分辨「这是父域那把尺子」与「这是分叉出来的、差异在此」——`domain_rubrics` 的既有纪律就是 fork 必须可审。缺 `fork_diff` 的 fork 在库里不可能存在（`ForkError` 挡着），所以投影只需如实带出。

## Risks / Trade-offs

- [两张表意味着两处版本序列] → 版本号按 `(domain, kind)` 独立单调，界面按种类分列，不合并计数；不承诺跨种类可比。
- [新拉取面扩大攻击面] → 种类白名单 + 沿用既有 token 三态校验 + 发布只读 + 足迹只增。
- [投影 SQL 写错会让 digest 变动但内容没变] → 幂等测试必须覆盖「同一内容两次发布」；另有一条测试把投影输出与 `canonical_digest` 的输入逐字段比对。
- [解除归属后已发布版本是否还可用] → 可用（spec 已有 requirement）；代价是「书架上看不到的尺子仍在被消费」，因此发布页必须显示该版本的归属现状。

## Migration Plan

1. 建两表（`asset_publications`、`asset_pull_events`），走 `ensure_schema`，纯新增不改既有表。
2. pack 注册 `rubric` / `sample` 投影；未注册时 `list_kinds()` 为空、进程正常启动。
3. 新路由挂上，`ontology` 路径行为不变（回归断言逐字节）。
4. legal 域发布一版 `rubric`，用已登记消费者拉取比对 digest。
5. 回退：从 pack 摘掉种类注册即可让发布/拉取两处都拒绝该种类；已发布行保留可查。
