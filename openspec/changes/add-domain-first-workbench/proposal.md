# 域优先工作台（Domain-First Workbench）

> 蓝图台账 **C5**。总纲：`docs/knowledge-platform-blueprint.md`。C1–C4 已把内核（模板/域/角色/创作台/分发契约/RAG 语料）全部上产；本 change 给这套内核装上**门面**——人第一次进来就能看见「我有哪些域」，进去就能把一个域的**本体与评测资产**看全、办完、发出去。

## Why

内核齐了，门不存在。今天真实的状态是：

- **没有入口**。`GET /` 直接 302 到 `/rubrics`——那是法律条线的评测尺清单，不是域的入口。登录后没有人知道自己「有哪些域」，只能记住 `/workbench/{domain_key}` 这种 URL。现网只有一个域（`legal`），所以没人喊疼；等银行/供应链/餐饮/酒店/证券几条线开域，第一句话必然是「我在哪儿进」。
- **导航是法律条线的形状，不是平台的形状**。顶栏是 11 条全局法律链接（尺/提示词/对比/法条/条款/合同/样例/评审/检索）+ 每个域两条链接（工作台、域管理）。域越多，顶栏越乱；而且这些链接与「你当前在哪个域」无关。
- **域不是一个上下文**。域 key 只出现在 URL 路径里，没有当前域、没有切换器、没有面包屑。同时处理几个业务域的 bench 和 ontology，人得自己在脑子里维护「我现在是谁的哪个域」。
- **一个域的四层本体没有一页能看全**。声明层（模板词表）、策展层（KU）、发布层（`ontology_publications` 的 version/digest/changelog）、消费层（登记消费者 + 拉取足迹）分布在四张表、三个页面或根本无页面。想知道「这个域本体到底建成什么样、哪层是空的」，答不出来。
- **评测资产没有域归属**。`rubrics`/`prompts`/`compares`/`samples`/`clauses`/`law_info` 全部按 `contract_type` 组织，与域完全无关。所以「不同业务领域的 bench」今天做不到——语义上分不开，页面上也分不开。
- **生产闭环反着走**。本体舰队的提案员把草案提交到**柏讯**的动作审批队列，平台自己确认不了自己的生产产物。这与蓝图铁律一「平台自成闭环，不依赖任何消费者的反向实时输入」相反，也与 C3 已裁的分发契约「wire 为 **seed 原料源**；**已发布本体的权威源是平台**」相反。
- **门在哪个域名上也没人知道**。`lawbench.finddatatech.cloud` 是控制台（需要登录），`bench.finddatatech.cloud` 是介绍页 + 公开 overview API；官网 `/products` 里没有「知验台」这一条。

## What Changes

**P0 — 门与域上下文（本 change 主体）**

1. **新落点 `/d`：我的域**。登录后的默认落点，替掉 `/rubrics`。列当前身份持有 active 成员身份的域（按最近使用排序），零域给诚实空态（等邀请 / 平台管理，仅 admin），域数字不造假。
2. **域内唯一入口 `/d/{domain_key}`：域控制台**。一个域一个上下文，常驻域切换器 + 面包屑，六区导航：总览 / 本体 / 评测 / 提案 / 发布 / 设置。区只按该身份在该域的角色渲染；平台级（模板、开域、全局邀请）不进域内导航，留在 admin 门。
3. **导航模型换形**：全局法律链接从顶栏降级为「法律条线的评测资产」（域内评测区 + 全局资产池两个入口）；顶栏只留：品牌（回 `/d`）、域切换、语言、身份。旧 URL 全部继续可用（不制造死链）。
4. **域本体台账 `/d/{key}/ontology`**：一页看全四层 + 一致性核对。只读投影，不建第二套发布面：digest 必须与分发拉取面返回的**同一个** digest。
5. **域提案箱 `/d/{key}/inbox`**：自动岗/专家草案落域内、负责人确认才走 `upsert_knowledge_unit`、驳回退回且同键不自动重提。
6. **落点互认**：介绍页 `bench.*` 与官网 `/products` 增加「进入控制台」入口；控制台登录页回链介绍页。（外仓：`fd-official-web`）

**P1 — 评测资产按域归属**

7. **资产归属登记（零内核改动）**：新增 `domain_assets` 归属表（`domain_key` + `asset_kind` + `asset_key`，多对多），给现有 rubric/prompt/compare/sample/clause/law_info 打域归属，回填法律域。**不改**任何既有表的主键/外键、不改既有 1000+ 测试的行为。
8. **域评测区 `/d/{key}/bench`**：按资产类型列归属本域的资产、未归属池、一键归属/解除；点进去仍是既有各资产页（不改其行为）。

**P2 — 生产闭环归位（跨仓）**

9. **舰队提案目标改为域提案箱**：`fleet → 平台域内提案箱`，柏讯审批队列不再新增该类提案。bench 侧提供提交面与幂等去重；fleet 侧切换属于伴随 change（`fd-wire`/`paas` 根），本 change 只定义契约与 bench 侧实现。

**P3 — 不做什么（写进 design 的边界）**

- 不做客户登录 UI：蓝图已裁「消费者（机器）版本化拉取，不登录 UI」；客户侧体验在柏讯。
- 不做消费者反向写回、不做自动修复不一致：台账只报事实与差集。
- 不合并 `lawbench.*` 与 `bench.*` 两个 host：改 host 会断外链与 Logto 回调白名单，收益不抵风险；改为双向互认入口。

## Capabilities

### New Capabilities

- `domain-console`: 域优先控制台——登录落点、我的域列表、域切换器与面包屑、域内六区导航、各区按域角色渲染、fail-closed 且零跨域泄漏。
- `domain-ontology-ledger`: 域本体台账——声明/策展/发布/消费四层一页对齐、模板词表与库内实际的一致性核对、发布版本历史与消费者拉取足迹（只读投影，不建第二发布面、不暴露明文凭据）。
- `domain-proposal-inbox`: 域提案箱——草案入箱携带来源与依据、负责人确认即经内核收口落库、驳回退回且同键不自动重提、待确认计数驱动总览。
- `domain-bench-catalog`: 域评测资产目录——资产归属登记（多对多，零内核改动）、域内按类型列出与归属/解除、未归属池。

### Modified Capabilities

- `web-rbac`: 「导航按域过滤」升级为「域优先导航」——全局条目不再随每个页面渲染；导航按当前域上下文与该域角色渲染，域列表只列 active 成员域，平台门只对 `admin`。请求与权限判定规则本身不变（平台 scope 先、域角色后，双闸不变）。

## Impact

**代码（本仓 `law-bench`）**

- 新增路由模块 `src/web/routes/console.py`（`/d`、`/d/{key}`、六区）、`src/bench/domain_assets.py`（归属登记）、`src/bench/proposals.py`（提案箱存储）；
- 新增模板 `domain_list.html`、`domain_console_*.html` 六个区页、`_domain_switcher.html`；改造 `base.html` 顶栏；
- 迁移：`domain_members.last_opened_at`、`domain_assets`、`domain_proposals`、`distribution_pull_events`；
- `src/web/routes/pages.py`：`/` 落点改 `/d`；`/workbench/{key}` 302 到 `/d/{key}`（兼容）；
- `src/bench/distribution.py`：拉取成功落 `distribution_pull_events`（append-only），不改 payload 契约；
- i18n：新增键（zh/en 成对），不硬编码文案。

**接口/契约**

- 分发拉取面 **payload 不变**（`fd-wire` 已按此落地 `legal v1`，digest `3586552a`）——本 change 只加读取侧足迹，不动契约；
- 新增内部提交面 `POST /api/d/{key}/proposals`（域 token / 岗位身份行），供 P2 舰队接入；幂等键 = `(domain_key, source, external_key, evidence_digest)`。

**跨仓**

- `fd-official-web`：`/products` 增「知验台」条目 + 控制台入口（P0 尾项）；
- `fd-wire` / `paas`：舰队提案目标切换（P2，独立 change）。

**风险**

- 顶栏换形是「所有页面的第一屏都变」，回归面广：P0 必须带全量 e2e 走查（浏览器导航链路），不能只跑单测；
- 归属表是**多对多**：同一 rubric 可属多域，页面不能假设唯一归属；
- 提案箱是**新的写面**：必须复用 `upsert_knowledge_unit` 与词表执法，禁止第二条写入路径。
