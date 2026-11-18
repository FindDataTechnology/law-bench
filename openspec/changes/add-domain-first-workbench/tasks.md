# Tasks: add-domain-first-workbench（C5）

> P0 拆到可执行粒度（文件级）。P1/P2 到任务级。任何 UI 页开工前先走 impeccable（§0.1）。
> 依赖顺序：0 → 1 → 2 → 3 → 4 → 5；P1/P2 在 P0 验收后另起。

## 0. 前置

- [x] 0.1 写 `.impeccable/surfaces/bench-domain-console.md`：Mode=Operate，Direction contract 承接 "The Evidence Ledger"，列管辖页组（/d、六区、switcher），Facts 声明「RBAC/路由/数据契约边界」
- [x] 0.2 迁移 DDL 进 `src/bench/workspace_store.py`（幂等：`domain_members.last_opened_at`、`domain_assets`、`domain_proposals`、`domain_proposal_events`、`distribution_pull_events` + 索引），确认 `ensure_schema` 一次建齐
- [x] 0.3 建 `src/bench/domain_assets.py`：`assign/list_for_domain/list_unassigned/unassign/purge_orphans`（纯存储，无路由）
- [x] 0.4 建 `src/bench/proposals.py`：`submit/list/get/confirm/reject` + `canonical_evidence_digest()`；`confirm` 内部只调 `authoring` 内核写服务（不写第二条 INSERT）
- [x] 0.5 建 `src/bench/ledger.py`：四个聚合查询 `declaration_layer / curation_layer / publication_layer / consumption_layer` + `reconcile()`（差集三类）
- [x] 0.6 域解析与上下文复用面确认：`workspaces.get_domain` / `list_domains(user_id=...)` / `get_active_role` / `_capability`（搬到 `src/web/domain_context.py` 供六区共用）；新增 `touch_last_opened(conn, domain_id, user_id)`
- [x] 0.7 i18n 新增键骨架（`nav.*`、`console.*`、`ledger.*`、`inbox.*`、`bench_catalog.*`）zh/en 成对落 `src/web/i18n.py`

## 1. P0-A 门与域上下文

- [x] 1.1 `src/web/routes/console.py`：`GET /d`（我的域列表；`last_opened_at DESC`；零域空态；admin 平台门）+ `domain_list.html`
- [x] 1.2 `GET /d/{domain_key}` 总览：状态卡（模板名/版本、KU 总数、最新发布版本、待确认计数、我的任务）+ `domain_console_overview.html`；打开时 `touch_last_opened`
- [x] 1.3 `_domain_switcher.html`：当前域 + 角色 + 切换下拉（只列 active 成员域）+ 面包屑「我的域 / 域 / 区」
- [x] 1.4 `_domain_zone_nav.html`：六区渲染，按 `_capability()` 过滤（annotator 只读区；expert +创作/提案；lead +确认/发布/指派/设置）
- [x] 1.5 `base.html` 改造：品牌 → `/d`；域页顶栏换成「域指示 + 切换 + 语言 + 身份 + 平台门」；11 条全局法律链接从顶栏移出（保留在全局资产池页与域评测区入口）
- [x] 1.6 `pages.py`：`/` 改 302 → `/d`；`/workbench/{domain_key}` 改 302 → `/d/{domain_key}`（保留既有 302/403 语义）
- [x] 1.7 区路由双闸：每区路由先 `require_scope('content:read')`，再域成员校验，再区角色校验；非成员 403 且模板不渲染域字段
- [x] 1.8 `GET/POST /d/{domain_key}/settings`：复用 C1 成员/邀请存储（`workspace_store`），lead/admin 门

## 2. P0-B 本体台账

- [x] 2.1 `GET /d/{domain_key}/ontology` + `domain_console_ontology.html`：四层区块，每层带来源标签与时间口径
- [x] 2.2 声明层：模板名/版本、`entity_types`、`relationship_kinds`、`tier_vocabulary`、`sensitivity_vocabulary`；无模板锚 → 指向平台门
- [x] 2.3 策展层：KU 总数、按 kind 分布（标注 entity/relationship lane）、按 tier 分布、最近 N 条 `authoring_events`
- [x] 2.4 发布层：最新 version/digest/published_at/changelog 摘要 + 历史版本列表；无发布 → 空态（lead/admin 给发布入口）
- [x] 2.5 消费层：`distribution_consumers`（名/域范围/创建/吊销状态）+ 每消费者最新 `distribution_pull_events`；无 → 空态说明「需先登记消费者」
- [x] 2.6 一致性核对区：零使用 kind、出表 kind（异常，给两条处置路径）、模板版本锚是否最新；一致时明说一致
- [x] 2.7 `distribution.py` 拉取成功处追加 `distribution_pull_events`（append-only；失败/未匹配不写）；payload 字节不变，加测试断言响应字段集合未变

## 3. P0-C 提案箱

- [x] 3.1 `GET /d/{domain_key}/inbox` + `domain_console_inbox.html`：pending/confirmed/rejected 三态列表（来源、kind、external_key 摘要、提交时间、依据摘要）
- [x] 3.2 `POST /d/{domain_key}/inbox/{id}/confirm`：lead/admin；调 `proposals.confirm` → `upsert_knowledge_unit`；写 `domain_proposal_events`；重复确认幂等
- [x] 3.3 `POST /d/{domain_key}/inbox/{id}/reject`：lead/admin + 理由必填；写事件；同键后续提交需新 `evidence_digest`
- [x] 3.4 `POST /api/d/{domain_key}/proposals`：内部提交面（域 token 或岗位身份行），幂等键 `(domain, source, external_key, pending)`；缺依据 → 400；跨域 → 403
- [x] 3.5 自提自确认禁令：`submitted_by == 当前身份` 时确认 403（平台 admin 例外，事件 note 标记 `admin-override`）
- [x] 3.6 单测：重复提交 3 次只有 1 条 pending；驳回后同 digest 拒、换 digest 收；出表 kind 确认被拒且库无变化
- [x] 3.7 总览待确认计数与提案箱 pending 行数同口径（同一查询函数），清零显示 0

## 4. P0-D 互认与兼容

- [x] 4.1 登录页回链介绍页（`bench.*`）；`base.html` 身份区增「关于知验台」外链
- [x] 4.2 `fd-official-web`（外仓）：`/products` 增「知验台」条目 + 「进入控制台」→ `lawbench.finddatatech.cloud/d`
- [x] 4.3 兼容表逐条验证：`/rubrics`、`/prompts`、`/compare`、`/samples`、`/clauses`、`/law-info`、`/law-references`、`/contracts`、`/review`、`/search`、`/dashboard`、`/admin/*`、`/workbench/{key}` 全部可达且权限判定不变
- [x] 4.4 双语文案复核：新键 zh/en 成对，无硬编单语；域名称/key 来自数据不进 i18n

## 5. P0-E 验收

- [x] 5.1 浏览器链路 e2e：登录 → `/d` → 进 legal → 总览 → 本体 → 提案 → 发布 → 设置 → 切换域（含零域身份空态、非成员 403 两条负例）
- [x] 5.2 digest 单源核对：台账显示值 == `GET /api/v1/distribution/legal/ontology` 的 `digest`
- [x] 5.3 全链真跑：专家提交 → 负责人确认 → `knowledge_units` 可检索 → `authoring_events` 有记录 → 提案箱 confirmed
- [x] 5.4 全量回归：`pytest`（现有 1000+ 测试）全绿；新增单测覆盖 §0.3/0.4/0.5 存储层
- [x] 5.5 临时第二域演练：用真库开一个临时域，验证域列表/切换器/台账空态零代码改动可用，演练后删除
- [x] 5.6 `openspec validate add-domain-first-workbench --strict` 过绿；写验收报告（逐条判据 + 证据）→ `acceptance.md`

## 6. P1 评测资产按域归属

- [x] 6.1 `GET /d/{domain_key}/bench` + `domain_console_bench.html`：按 `asset_kind` 分组列示（名/标识/跳转既有资产页）+ 未归属池（按类型筛选）
- [x] 6.2 `POST /d/{domain_key}/bench/assign` / `unassign`：lead/admin；幂等；解除不改资产
- [x] 6.3 资产清单适配器：为每类资产提供 `list_keys()` / `display_name(key)`（`src/bench/asset_catalog.py`），避免把六张表的查询散进路由
- [x] 6.4 回填脚本 `scripts/backfill_domain_assets.py`：显式清单（非「全部归 legal」）+ 幂等 + dry-run 输出计数
- [x] 6.5 孤儿处理：列示时 left join 资产表，缺失标「资产已不存在」+ `purge_orphans` 入口
- [x] 6.6 判据测试：同一尺归属 A+B，解除 A 后 B 仍列出；回填两次只一行；归属前后评测结果一致（断言归属不进提示词/判据/结果）

## 7. P2 跨仓：舰队提案目标切换

- [x] 7.1 本仓：`POST /api/d/{key}/proposals` 契约文档化（字段、幂等键、错误码、鉴权与关系类端点要求）
  → `docs/domain-proposal-contract.md`；`tests/test_domain_proposal_contract_doc.py` 双向校验文档与代码不漂
- [ ] 7.2 伴随 change（`fd-wire`/`paas` 根，另立）：舰队提案岗提交目标从柏讯审批队列切到域提案箱；柏讯审批队列不再新增该类提案
- [ ] 7.3 判据：舰队一轮真跑 → 域提案箱出现 pending；柏讯审批队列零新增；同键重复提交幂等

## 8. 挂账（本 change 不处理，仅登记）

- [ ] 8.1 `cadence.turnTimeoutMs` 被 `task-engine.js:683` 硬编码 600s 覆盖 —— paas 发布时修
- [ ] 8.2 星妍→柏讯供给面摄取停在 2026-11-02 —— 独立处理
- [ ] 8.3 客户登录 UI / 消费者反向写回 —— 按蓝图 D9 明确不做

## 9. 上产（2026-11-08 真机滚版发现并修）

> 承 §0.2 的「`ensure_schema` 一次建齐」：本机与测试库靠 fixture 显式调用 `ensure_schema`，
> 生产库从来没有这一步 —— 上产后第一次真登录才发现。

- [x] 9.1 生产库真身核对：`law_bench` 只有 `domains`/`domain_members`（旧形），缺
  `last_opened_at` 与 C5 的六张表；判据 = 登录态访问 `/d` 整页 500
  `column m.last_opened_at does not exist`
- [x] 9.2 修因：新增 `src/eval/bootstrap.py`（`ensure_schema` 的启动壳，失败即非零退出），
  `scripts/docker-entrypoint.sh` 在 origin 分支 `exec uvicorn` 之前无条件执行；
  public 只读分支**不跑** DDL（那边是 dump 副本，读面不许改结构）
- [x] 9.3 单测 `tests/test_boot_schema.py`：空库跑 boot 步骤必须建齐六表 + 列（跨新连接复核已提交）、
  重复执行幂等、库不可达必须非零退出、entrypoint 两分支的静态断言
- [x] 9.4 线上补账：pod 内对生产库执行一次 `ensure_schema`，复验六表 + `last_opened_at` 就位
- [x] 9.5 线上验收（登录态真请求）：`/d` 200「我的域」空态；`/d/legal` 及本体/评测/提案/发布/设置
  六页全 200 且标题正确；旧深链 `/workbench/legal/...` 302；匿名 `/d` 仍 401
