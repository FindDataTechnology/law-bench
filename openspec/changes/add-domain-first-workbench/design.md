# 设计：域优先工作台（C5）

> 总纲 `docs/knowledge-platform-blueprint.md`（平台宪法，已裁 2026-11-05）。本 design 是它的 **C5**：
> C1–C4 把内核建完（模板/域/角色/创作台/分发契约/RAG 语料），C5 建**门面与资产视图**。

## 1. 问题不是「少了功能」，是「建好了但没有入口」

一句话：**知验台今天是一台装好的机器，正面没有门，控制面板贴的是法律条线的标签。**

用户原话：「我甚至不知道在哪里可以登录」「并处理不同业务领域的 bench 和 ontology」。这两句正好指向两个结构性缺陷：**门缺失**、**资产没有按域组织**。

## 2. 现状测绘（2026-11-08 实探，不是推测）

| 观测 | 事实 | 后果 |
|---|---|---|
| `GET /` | `pages.py:53` 无条件 `RedirectResponse("/rubrics")` | 登录后落到法律尺清单，没有任何「我的域」概念 |
| 顶栏 | `base.html` 11 条全局法律链接 + 每域 2 条链接（工作台、域管理） | 域越多越乱；全局链接与当前域无关 |
| 域坐标 | 域 key 只存在于 URL 路径 `/workbench/{key}` | 没有当前域、切换器、面包屑；多域作业靠人脑维护上下文 |
| 域名分工 | `lawbench.*` = 需登录的控制台；`bench.*` = 介绍页 + `/api/public/overview` | 两个 host 互不指路；官网 `/products` 无「知验台」 |
| 现网规模 | 1 个域（`legal`）、1 个模板（`legal-domain` v1） | 今天就一个域，所以没人喊疼；多域一开立刻痛 |
| 本体四层 | 声明=模板行；策展=`knowledge_units`(namespace)；发布=`ontology_publications`；消费=`distribution_consumers` | 四层分散在三个页面或根本没有页面；`consumers` 无拉取时间 |
| 评测资产 | `rubrics`/`prompts`/`compares`/`samples`/`clauses`/`law_info` 均按 `contract_type` 组织，**无 domain 列** | 「不同业务领域的 bench」在数据层不存在 |
| 生产链路 | 舰队提案岗提交到**柏讯**动作审批队列 | 平台确认不了自己的生产产物，与铁律一相反 |
| 身份 | 平台 scope 来自 Logto（`bench` client）；域角色来自 `domain_members`；双闸先 scope 后域角色 | 基础已经对，不需要重建，直接复用 |

**因此本 change 的主体是 IA 与读投影，不是重写内核。** 唯一新增写面是提案箱，且必须复用内核唯一写路径。

## 3. 设计原则

承接蓝图三铁律，另加本 change 的三条自约束：

1. **平台自成闭环**：生产确认在平台内完成，不依赖消费者反向输入。
2. **多角色是前提**：每个区都按「该域内的角色」渲染，不是按平台角色。
3. **松耦合分发**：分发契约不动，`fd-wire` 已落地 `legal v1`（digest `3586552a`），本 change 不得破坏。
4. **域是唯一上下文**：任何域内页面都能回答「谁的哪个域、我在这里是什么角色」。不满足这条的页面算缺陷。
5. **缺口必须显式**：没有发布就说没有发布，没有消费者就说没有消费者。空态永远指路，永不造假（沿用 `polish-bench-workbench` 的诚实空态基线）。
6. **不加第二真源**：四层台账全部读既有表；digest 单源；提案箱只做流程，不做本体存储。

## 4. 信息架构

```
/                                     → 302 → /d
/d                                    我的域（域列表；零域空态；admin 平台门）
/d/{domain_key}                       总览
/d/{domain_key}/ontology              本体台账（四层 + 一致性核对）
/d/{domain_key}/bench                 评测资产（按类型分组 + 未归属池）[P1]
/d/{domain_key}/inbox                 提案箱（pending / confirmed / rejected）
/d/{domain_key}/publish               发布（版本历史 + 消费者 + 拉取足迹）
/d/{domain_key}/settings              设置（成员 / 角色 / 邀请）

/platform/templates                   模板管理        ┐
/platform/domains                     开域与全量域管理  ├ admin 门（沿用既有 /admin/*）
/platform/invitations                 跨域邀请        ┘

全局资产池（域上下文之外，保持既有路径）：
/rubrics /prompts /compare /samples /clauses /law-info /law-references
/contracts /review /search /dashboard
```

**页面骨架**（每页同一套壳）：

```
┌ 品牌(→/d)   当前域 ▾ [切换]   [语言]   [身份/登出]   [平台门·仅 admin] ┐
├ 面包屑：我的域 / <域名称> / <区>                                       │
├ 区内导航：总览 · 本体 · 评测 · 提案 · 发布 · 设置（按域角色过滤）        │
└ 内容                                                                  ┘
```

**为什么六区而不是更多**：六区正好对应一个人在一个域里要办的五件事（看清状态、管本体、管评测资产、处理待确认、发出去）+ 一处管理（设置）。再多就是子页，不该进一级导航。

**为什么「协作」不单列**：既有「我的任务 / 指派」是**在这个域里办事**的一部分，放在总览第一屏（负责人可见指派按钮），比藏在第七个导航项里更符合使用频率。既有 `expert-authoring`「任务指派与工作台」的四要素（我的任务、域内容浏览、编辑入口、事件流查看）在新的位置全部保留：我的任务与指派→总览；浏览与编辑→本体区；事件流→本体区资产页 + 总览最近变更。

## 5. 决策

### D1 门建在 `law-bench` 内，不新开服务、不新开仓

**选择**：域控制台就是本仓的新的路由组。

**备选**：① 新建 `bench-console` 前端仓（React）；② 在柏讯控制台加一个「本体」页签。

**被否理由**：① 本仓已有完整 Jinja 呈现层 + 双语 + RBAC 依赖注入，新仓要把双闸、i18n、模板语义全部重建一遍，且会分裂「谁能看域内容」的判定；② 柏讯是消费侧，蓝图已裁权威源在平台，把生产门放进消费侧会把方向彻底搞反。

### D2 域上下文 = 路径 + 服务端解析，不做「当前域」会话状态

**选择**：`/d/{key}/...`，每次请求由服务端按 key 取域、校验成员资格、算域角色。

**备选**：① 会话里存 `current_domain`，路径不带域；② 子域名 `{key}.bench...`。

**被否理由**：① 会制造「URL 与上下文不一致」的经典缺陷（分享链接打开的是别人的域），且多标签页作业必然串域；② 子域名要泛解析证书 + Logto 回调白名单扩张，运维成本远超收益。

### D3 六区导航按「该域内的角色」渲染，平台门独立

**选择**：域内导航只表达域内六区；模板/开域/跨域邀请留在 `/admin/*` 平台门，只在 `admin` scope 下渲染。

**理由**：`web-rbac` 已有的双闸判定完全够用，问题只在渲染层把两件事混在一起。分开后，「谁是平台管理员」和「我在这个域能干什么」不再互相污染。

### D4 本体台账是纯读投影，digest 单源

**选择**：四层全部读既有表；`digest` 直接取 `ontology_publications` 行内值，与 `GET /api/v1/distribution/{key}/ontology` 返回的同一版本 digest 必须相等。

**代价/收益**：不做任何缓存或二次计算，页面多几次查询（可接受：一次请求 4 条聚合查询）；换来「台账说 v2 digest X，消费者拉到的就是 X」这条可核对事实。

**被否**：在台账里显示「本地重算的摘要」——一旦与发布时摘要不同，人会不知道该信哪个。

### D5 提案箱是新写面，但只有一条落库路径

**选择**：新增 `domain_proposals` + 状态历史；确认动作内部调用 `upsert_knowledge_unit`，与既有创作面**同一个函数**。

**关键规则**（写进 spec）：
- 幂等键 `(domain_key, source, external_key, state='pending')` → 重复提交返回同一条；
- 驳回后，同 `(source, external_key)` 只有携带不同 `evidence_digest` 才可重提（防刷屏）；
- 禁止自提自确认（`expert` 提交、`lead` 确认），平台 `admin` 例外但必须留痕。

**被否**：提案另存一份「草案本体」再迁移——会出现两套本体表示，违背「唯一写路径」。提案表只存**提交物快照 + 流程状态**，不参与检索。

### D6 评测资产用「归属登记」，不改任何资产表

**选择**：新表 `domain_assets(domain_key, asset_kind, asset_key)`，多对多；资产页与评测执行零改动。

**为什么不给每张表加 `domain_key` 列**：
- 六张表 + 相关查询 + 1000+ 测试全要动，回归面巨大；
- 现实是**多对多**：一把通用合同法尺同时服务法律域和供应链域是常态，单列强绑定会逼人复制资产；
- 蓝图铁律「内核零改动」的同一精神：内容归属是目录层的事，不是内容层的事。

**代价**：跨域聚合查询要走 join；归属没有强一致校验（资产被删后留孤儿行）→ 用「列示时 left join 资产表，孤儿行标注『资产已不存在』」处理，并给清理入口。

### D7 拉取足迹用 append-only 事件表，不写 consumers 行

**选择**：`distribution_pull_events(consumer_id, domain_key, version, happened_at)`，拉取成功时追加；台账按事件表取每消费者最新一条。

**为什么不加 `last_used_at` 列**：可审计性（能回答「上周谁拉过 v1」）和并发安全（append-only 无更新竞态）；`public_overview` 刻意不写库的约定也不被破坏（它是另一个路由，且显式声明不触碰凭据）。

### D8 两个 host 不合并，做双向互认

**选择**：`bench.*`（介绍页 + 公开 overview）加「进入控制台」按钮 → `lawbench.*/d`；控制台登录页回链介绍页；官网 `/products` 补「知验台」条目（外仓任务）。

**被否**：把控制台迁到 `bench.*` 或反向合并——会断外链、要改 Logto redirect 白名单与反代规则、收益只是「一个域名」，不值。

### D9 明确不做

| 不做 | 理由 |
|---|---|
| 客户登录 UI | 蓝图已裁：消费者（机器）版本化拉取，不登录 UI；客户体验在柏讯 |
| 消费者反向写回 / 平台接受外部写入 | 铁律一 |
| 台账自动修复不一致 | 修复必须有人负责；自动改本体是不可逆操作 |
| 客户端维护「当前域」 | D2 |
| 评测资产表加域列 | D6 |
| 新前端框架 | D1 |

## 6. 数据模型（迁移清单）

```sql
-- 1) 最近打开时间（域列表排序；不含业务语义）
ALTER TABLE domain_members ADD COLUMN IF NOT EXISTS last_opened_at TIMESTAMPTZ;
-- 读域页面时 UPSERT：UPDATE domain_members SET last_opened_at=now()
--   WHERE domain_id=$1 AND user_id=$2 AND removed_at IS NULL
-- （按人按域一行，写放大可忽略；非内容写，不产生 authoring_event）

-- 2) 评测资产归属（D6）
CREATE TABLE IF NOT EXISTS domain_assets (
    domain_id  BIGINT NOT NULL REFERENCES domains(id),
    asset_kind TEXT   NOT NULL,          -- rubric|prompt|compare|sample|clause|law_info|...
    asset_key  TEXT   NOT NULL,          -- 资产自身标识（name/slug/id 的稳定文本形）
    added_by   TEXT   NOT NULL,
    added_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (domain_id, asset_kind, asset_key)
);
CREATE INDEX IF NOT EXISTS domain_assets_asset_idx ON domain_assets (asset_kind, asset_key);

-- 3) 提案箱（D5）
CREATE TABLE IF NOT EXISTS domain_proposals (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain_id       BIGINT NOT NULL REFERENCES domains(id),
    source          TEXT NOT NULL,       -- 'fleet:<post>' | 'human:<sub>' | 'expert:<sub>'
    kind            TEXT NOT NULL,
    external_key    TEXT NOT NULL,
    body            TEXT NOT NULL,
    evidence        JSONB NOT NULL,      -- 数据集/列/列级证据或引用 KU
    evidence_digest TEXT NOT NULL,       -- sha256(canonical evidence)
    impact          TEXT NOT NULL,
    state           TEXT NOT NULL DEFAULT 'pending'
                    CHECK (state IN ('pending','confirmed','rejected')),
    submitted_by    TEXT NOT NULL,
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_by      TEXT,
    decided_at      TIMESTAMPTZ,
    decision_note   TEXT
);
-- 幂等：同一来源同键只允许一条 pending
CREATE UNIQUE INDEX IF NOT EXISTS domain_proposals_pending_uk
    ON domain_proposals (domain_id, source, external_key) WHERE state = 'pending';
CREATE INDEX IF NOT EXISTS domain_proposals_box_idx
    ON domain_proposals (domain_id, state, submitted_at DESC);

-- 4) 提案状态历史（append-only，spec「状态历史不可改写」的载体）
CREATE TABLE IF NOT EXISTS domain_proposal_events (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    proposal_id BIGINT NOT NULL REFERENCES domain_proposals(id),
    from_state  TEXT,
    to_state    TEXT NOT NULL,
    actor       TEXT NOT NULL,
    note        TEXT,
    happened_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 5) 拉取足迹（D7，append-only）
CREATE TABLE IF NOT EXISTS distribution_pull_events (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    consumer_id BIGINT NOT NULL REFERENCES distribution_consumers(id),
    domain_key  TEXT NOT NULL,
    version     INT  NOT NULL,
    happened_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS distribution_pull_events_consumer_idx
    ON distribution_pull_events (consumer_id, happened_at DESC);
```

迁移方式沿用既有幂等 DDL（`ensure_schema`，`CREATE ... IF NOT EXISTS` + `ALTER ... ADD COLUMN IF NOT EXISTS`），不引入迁移框架。

## 7. 路由与页面

| 路由 | 方法 | 权限 | 模板 | 说明 |
|---|---|---|---|---|
| `/` | GET | 登录 | — | 302 → `/d` |
| `/d` | GET | 登录 | `domain_list.html` | 我的域；零域空态；admin 平台门 |
| `/d/{key}` | GET | 域成员 | `domain_console_overview.html` | 状态卡 + 我的任务 + 待确认计数 + 最近变更 |
| `/d/{key}/ontology` | GET | 域成员 | `domain_console_ontology.html` | 四层台账 + 一致性核对 |
| `/d/{key}/bench` | GET | 域成员 | `domain_console_bench.html` | 分组列示 + 未归属池（P1） |
| `/d/{key}/inbox` | GET | 域成员 | `domain_console_inbox.html` | 三态列表 |
| `/d/{key}/inbox/{id}/confirm` | POST | lead/admin | — | 确认落库 |
| `/d/{key}/inbox/{id}/reject` | POST | lead/admin | — | 驳回 |
| `/d/{key}/publish` | GET | 域成员 | `domain_console_publish.html` | 版本历史 + 消费者 + 足迹 |
| `/d/{key}/publish` | POST | lead/admin | — | 调既有发布函数（不新增发布实现） |
| `/d/{key}/settings` | GET/POST | lead/admin | `domain_console_settings.html` | 成员/角色/邀请（复用 C1 存储） |
| `/d/{key}/bench/assign` `/unassign` | POST | lead/admin | — | 归属/解除 |
| `/workbench/{key}` | GET | 域成员 | — | 302 → `/d/{key}` |
| `/api/d/{key}/proposals` | POST | 域 token / 岗位身份行 | — | 舰队提交面（P2 用，P0 即可用） |

复用既有能力，不重写：域解析 `workspaces.get_domain` / `list_domains` / `get_active_role`；发布 `bench.distribution.publish`；落库 `authoring` 的写服务；成员与邀请 `workspace_store`。

## 8. 权限矩阵

| 能力 | annotator（审核标注员） | expert（领域专家） | lead（领域负责人） | platform admin |
|---|---|---|---|---|
| 看见域 / 切换 | ✅ | ✅ | ✅ | ✅（全量域） |
| 总览 | ✅ | ✅ | ✅ | ✅ |
| 本体台账（读） | ✅ | ✅ | ✅ | ✅ |
| 本体创作 / 提案提交 | — | ✅ | ✅ | ✅ |
| 提案确认 / 驳回 | — | — | ✅ | ✅（须留痕） |
| 发布 | — | — | ✅ | ✅ |
| 评测资产归属 | — | — | ✅ | ✅ |
| 域设置（成员/邀请） | — | — | ✅ | ✅ |
| 平台门（模板/开域/跨域邀请） | — | — | — | ✅ |

规则不变的部分：平台 scope 先判、域角色后判、双闸都过才执行；非成员一律 fail-closed。

## 9. 呈现与 i18n

- 全部走 **impeccable** 流程（`AGENTS.md` 用户裁决：改 UI 一律走 impeccable）。P0 开始前先落 `.impeccable/surfaces/bench-domain-console.md`（Mode=Operate），承接既有 "The Evidence Ledger" 设计系统，不另起炉灶。
- 新页面必须满足既有基线：loading/empty/error 三态齐全、空态诚实且指路、表单 label 完整、980px 单列不破版、zh/en 键成对（`web-i18n` 口径）。
- 新文案全部进 `src/web/i18n.py`，不硬编码；域名称与 key 是数据不是文案。

## 10. 兼容、迁移、回填

- **零死链**：既有全部路径保持可用；`/workbench/{key}` 302；`/admin/*` 不变；资产页行为不变。
- **回填**：`legal` 域在迁移后由一次性脚本归入既有评测资产（幂等，重复执行不产生重复行）；回填清单由显式列出而非「全部归 legal」，避免把未来的非法律资产误归。
- **不迁移任何本体数据**：KU 的 namespace 已经是域 key，无需搬。

## 11. 分期与验收判据

| 期 | 内容 | 判据（可核对） |
|---|---|---|
| **P0**（本 change 主体） | `/d` 门 + 六区 + 本体台账 + 提案箱 + 互认入口 | ① 浏览器从 `/` 一路点进 `legal` 域并看到四层台账，无手写 URL；② 台账 digest = 拉取面 digest；③ 专家提交提案 → 负责人确认 → 实体可检索且事件流有记录；④ 非成员访问域 URL 403 且零字段泄漏；⑤ 既有 1000+ 测试全绿 + 顶栏换形的 e2e 走查 |
| **P1** | 评测资产归属 + 域评测区 + 回填 | ① legal 域评测区列出回填资产且计数可核；② 同一尺归属两域，解除一侧不影响另一侧；③ 评测执行结果与改动前一致 |
| **P2** | 舰队提案目标切换（跨仓） | ① 舰队提案落域提案箱，柏讯审批队列不新增该类提案；② 同键重复提交幂等 |
| **P3** | 多域扩线（银行/供应链/餐饮/酒店/证券） | 开第二个域后，域列表与切换器在零代码改动下可用 |

## 12. 风险与未知

| 风险 | 影响 | 处置 |
|---|---|---|
| 顶栏换形影响所有页首屏 | 回归面最广的一处 | P0 必须跑浏览器链路 e2e，不只单测；先做 `/d` + 一个域页，再切顶栏 |
| 提案箱成为新的写面 | 若绕过内核会分裂本体 | 代码层把确认动作限制为调用 `upsert_knowledge_unit` 的单一函数，加单测断言「无第二条 INSERT INTO knowledge_units」 |
| `domain_assets` 归属是弱引用 | 资产删除后留孤儿 | 列示时 left join + 标注「资产已不存在」+ 清理入口 |
| `evidence_digest` 口径需固定 | 否则「新证据」判定随实现漂移 | 定义 canonical JSON（键排序、去空白）并写进单测 |
| P2 跨仓 | 舰队侧不切则闭环只完成一半 | 本 change 提供提交面 + 幂等契约；P2 另立 change（见 §13） |
| 现网只有 1 个域 | 多域路径未经验证 | P3 判据要求「开第二个域零代码改动可用」；P0 用真库 + 临时第二域演练后删除 |

## 13. 挂账与伴随 change

| 项 | 归属 |
|---|---|
| 舰队提案目标切换（`fleet → 域提案箱`） | 伴随 change：`fd-wire`/`paas` 根，P2 另立 |
| 官网 `/products` 增「知验台」条目 | 外仓 `fd-official-web`，P0 尾项 |
| `cadence.turnTimeoutMs` 被 `task-engine.js` 硬编码 600s 覆盖 | 既有挂账（paas 发布时修），与本 change 无关，此处仅登记不重复处理 |
| 星妍→柏讯供给面摄取停在 11-02 | 既有挂账，与本 change 无关 |
