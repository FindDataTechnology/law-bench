# 知验台整体解决方案 —— 多领域知识生产、质量与分发平台

> 状态：已裁（2026-11-05，用户确认「你决定吧」授权分期/隔离粒度/RAG 位三项裁决）
> 地位：平台宪法。后续所有平台类 change（C1-C4 及之后）以本文档为总纲；与本档冲突的旧 spec 条款以本档方向为准，修订落在对应 change 内显式完成。

## 一、平台定位

**以领域模板为骨架、行业专家长期维护为生产方式、四层质量体系为闸门、版本化发布-拉取为分发契约**，承载各领域的本体（领域数据语义层）与 RAG 知识资产，供多个消费方（fd-wire/柏讯是第一个，绝不是唯一）本地独立处理。

三条铁律：

1. **平台自成闭环**——生产工作全部在平台内独立完成，不依赖任何消费者的反向实时输入；
2. **多角色是前提**——不同行业的专家以邀请制进入、长期维护内容，角色体系不是附加功能而是平台成立条件；
3. **松耦合分发**——消费者拉取版本化快照落本地自行处理，升级自主；平台与消费者之间只有「拉取」一条细线。

## 二、平台承载什么（四类知识资产，一套内核）

```
                    知验台平台内核（领域无关，已在产）
          KU 类型化 · tier 四层 · 溯源守卫 · 升格 · 域包插拔 · meta-eval
 ─────────────────────────────────────────────────────────────────
 ① 本体（领域语义层）    ② RAG 知识资产         ③ 评测资产（尺子）      ④ 微调数据
    实体类型词表            语料文档/chunk KU      金集（文本 QA）        gold/silver 导出
    实体/概念/指标          嵌入/检索面            DQA 数据金集           finetune 飞轮
    关系/crosswalk          带四层溯源的 RAG 库     rubric 库
 ─────────────────────────────────────────────────────────────────
 四类资产共享同一套身份、质量档位、事件流、发布机制
```

- ① 本体：实体类型词表（entity-identity 词表模式）、实体/概念/指标、关系与 crosswalk；
- ② RAG：**资产位自 P0 天然成立**（内核 KU 本就承载 chunk/条款，法律域存量即活的 RAG 资产）；`rag-search` 由合同文档专用升为按域配置的通用语料服务（P2 落地）；
- ③ 尺子：金集、rubric、DQA 数据金集、meta-eval 校准；五仓散落尺子（fd-sentiment、fd-text-core、KG 车道判据、dashboards finalize 闸、fd-data-quality baselines）分批迁入（P3）；
- ④ 微调：finetune 飞轮已归档，随域包输出。

## 三、多领域架构（域包 = 模板实例）

- **领域模板**（模板工作，平台核心产出物）：本体模板（实体类型/概念结构/关系种类/档位与 sensitivity 词表）+ 语料模板 + 审核 rubric，三件套打包为域包骨架；
- **领域工作区**：**一域一工作区**（已裁）——成员、任务、内容、发布流完全隔离；跨域共享只经内核机制（共享 KU 类型、共享 rubric 库）；
- **模板是分层的**（2026-11-19 补，见 `docs/domain-template-layers.md`）：`foundation` / `observation` / `industry` / `domain` 四层，**层内可 `extends`（只增不删）、跨层只能 `aligned_with`（声明对齐，不合并词表）**。原因：观测词表（protocol 的 30 类）与业务本体（客户/科目/分录）是同一个所指的不同生命周期，合并必须选一个权威而两侧都能举出反例。**接一个新 ERP 厂商不产生新模板，只产生 crosswalk 行**——模板数 = 行业数（个位数），映射数 = 厂商数（会长）。
- 内核零改动：新增域 = 实例化模板 + 开工作区，不改内核代码（`bench-platform` 域包插拔契约保证）；
- 首批：法律（存量迁入）→ 柏讯数据域（wire）→ 政务/金融/跨境。

## 四、角色体系

| 角色 | 职责 |
|---|---|
| 平台管理员 | 模板管理、开域、邀请成员、发布审批 |
| 领域负责人 | 本域结构裁决、质量终审 |
| 领域专家（邀请制、长期） | 内容创作与持续维护（本体 + RAG 语料） |
| 审核/标注员 | 盲标、核验、一致性 |
| 消费者（机器） | 版本化拉取，不登录 UI |

运营机制：任务指派/队列、贡献归因（溯源四层天然记人）、一致性统计即专家质量分、吞吐计量（人工 gold 吞吐是平台最值钱资源）。

## 五、生产流水线

```
 seed 喂入 ──→ AI 预处理 ──→ 专家创作/维护 ──→ 质量闸 ──→ 发布 ──→ 消费者拉取 ──→ 本地处理
 (爬虫/wire 实体/   (预标注/嵌入/      (创作台，长期)      (升格+DQA    (版本+digest)   (版本 API)     (wire 落库/
  法律语料)          抽取)                                 +meta-eval)                                自行消化)
      ▲                                                                                    │
      └────────────────────── 反馈回路：drift / 消费者需求单 / 专家复核 ◄──────────────────────┘
```

现有 wire 升格-回写环不废：降位为「seed 喂入 + 质量闸」的内部环节。

## 六、分发契约

- 版本化发布：本体 / RAG 语料 / 金集三类均可发布，digest + changelog（模式照 wire ontology versioning 0049）；
- 拉取 API：机器凭据（`X-Internal-Token` 同款模式）+ 消费者登记 + 版本选择，json/yaml；
- **契约修订（随 P1 落地）**：`bench-platform` spec 现行「wire 为实体身份主键源（知验台不另存本体身份）」修订为——wire 为 **seed 原料源**；**已发布本体的权威源是平台**；
- 消费者本地侧：wire 拉取后落自身语义层存储（entity-layer/目录），本地版本化（0049 已有）自行管理。

## 七、分期路线（已裁）

| 期 | 内容 | 交付判据 |
|---|---|---|
| **P0 平台奠基** | 模板系统 + 领域工作区 + 邀请/角色 + 管理门页面 | 法律域模板实例化，管理员能邀人进域 |
| **P1 柏讯域包全链** | 本体模板→专家维护→发布→wire 拉取落库；主键源条款修订 | wire 拉到 v1 本体快照并落库 |
| **P2 RAG 服务通用化** | rag-search 按域语料/嵌入/检索 + DQA 数据金集 + 法律存量迁移入域包 | 柏讯域 RAG 可检索、法律零回归 |
| **P3 尺子归一** | 五仓散落尺子迁入为域评测资产 + meta-eval 全量 | 一处管所有尺子 |

> 2026-11-06 终态：P0/P1/P2 全部上 spec；P3 主刀（五仓尺子迁入、meta-eval 漂移脚本）早已完成，**唯一未销账=判官 4.1 验收判据**（结构性误读已堵、分层门与采样一致率通道已上 spec，但无候选通过分层门、relay 退化致全量 bake-off 未跑通——4.1 保持不勾，见台账 P3 两行）。

> **2026-11-18 补一阶（原分期表外）：跨线可比性**。P3 把尺子归一到了一个地方，但没有让**结论**可比——六条线各有一套门与落点，一行结论结构上无法与另一行放进同一张图。`add-eval-verdict-ledger` 补的就是这一阶：一条记录带 subject/ruler 地址、四道门闭集、三态结局、baseline 引用；`inconclusive`（判不出来）与 `fail`（判失败）在记录层就分开，从而无法被晋升闸误放行；未过校准门的判官产出 `provisional` 结论，不足以单独构成晋升依据——**判官 4.1 未销账这件事因此从「一句挂账」变成「结构性约束」**，不再依赖每次评审时有人记得。

## 八、Change 台账

| Change | 内容 | 期 | 状态 |
|---|---|---|---|
| C1 `add-ontology-template-and-workspaces` | 模板一等物 + 领域租户 + 邀请/角色 + 管理门页面 | P0 | ✅ 已归档上 spec（2026-11-06，16/16，回归 1199 绿） |
| C2 `add-expert-authoring-surface` | 模板实例化创作台 + 任务指派 + 变更事件流 | P0/P1 | ✅ 已归档上 spec（2026-11-06，15/15，回归 1233 绿） |
| C3 `add-knowledge-distribution-contract` | 发布-拉取契约 + 消费者登记 + wire 拉取客户端 + 主键源条款修订 | P1 | ✅ **全链收口（2026-11-06）**：bench 侧归档上 spec；wire 侧 `add-bench-ontology-pull-client` 实弹——生产滚 sha-53a9513/beae0a，legal v1（digest 3586552a）跨 ns 真拉落库幂等，投影可查，失败纪律实弹验证。P1 判据「wire 拉到 v1 本体快照并落库」✅ |
| C4 `add-domain-rag-corpus-service` | RAG 语料服务通用化 + 按域配置 | P2 | ✅ 已归档上 spec（2026-11-06，13/13，回归 1311 绿；rag-corpus-service 新建 + rag-search +1 域归属需求） |
| P3 `add-judge-misread-remediation` | 判官结构性误读 fail-loud + prompt 域化补账 + 校准闭环实跑 | P3 | 🟡 9/10（strict 绿）：3.2/3.3 已勾（run 8：误读清零达成、all_pass 0.602<0.70）；**4.3 未勾=4.1 未达成**，差距与边界如实挂账 |
| P3 `add-judge-model-selection` | 采样一致率置信通道 + 分层校准门（balanced_accuracy≥0.70）+ bake-off 留痕 | P3 | ✅ 已归档上 spec（2026-11-06，12/12，`judge-channel-selection` +4 需求入主 specs，全量 1325 绿）；bake-off 如实：relay 退化致 k=5 全量轮未跑通、48 条定界 pilot 全 vote_share、无候选过门（采样不稀释判官过严偏置），生产判官未切换 |
| P3 解禁路径（待拍板） | ①绑更强/更稳定判官上游 ②判官口径与 gold「过严」偏差另立校准轮 ③维持 silver-only | P3 | ⏸ 未开：4.1 挂账不销，选型轮已把差距定谳为链路级而非 prompt 级 |
| C5 `add-domain-first-workbench` | 域优先工作台：`/d` 我的域、域控制台六区导航、本体台账、域提案箱、评测资产按域归属 | P0/P1 | 🔄 51/56：六区与导航、台账、提案箱、资产归属已上产；剩余 7.2/7.3（舰队提案目标改域提案箱，跨仓）与 8.x（paas 侧 timeout、星妍供给面） |
| C6 `add-corpus-document-adoption` | 大库→子域取材：语料文档目录（按文档而非按块、派生不落表）、来源自述文档结构、取文档/取条款进本体（确定性切分、逐字原文、批量事务） | P2 | ✅ **已归档上 spec（2026-11-10，26/26，回归 1679 绿，specs 76/0）**：生产滚 sha-cf858e9。取入民法典 1208 条 + 合同法 428 + 公司法 266 条（含配套规定 13+8）；目录 468 篇（partial=false）；defines 闭环实测 concept + defines→民法典#第585条 双 pending、bad_endpoint=0。过程中修掉四类真问题：批次不收敛、两处 1000 行上限被当全集、条款父键只从块标题推导（新增 `<文档名>#第N条` 显式寻址） |
| C7 `add-domain-agent-team` | 智能体团队：七岗契约 + 权限矩阵/硬停清单 + 运行台账（四态） + 六项质量比 + 质量缺口可派单 + 岗位参数进 pack + 只读岗（巡检/质检）+ 确定性写（取材/结构）+ 只提案（概念）+ 跨生产者去重 + 值班长视图 | P2 | ✅ **已归档上 spec（2026-11-10，48/48，回归 1895 绿，specs 79/0）**：生产滚 sha-eaac09c。岗位真跑过：巡检派单 1 条（quality:grounding→agent:concept）、质检把 48 条待确认分为quote_unverifiable 41 / endpoint_open 4 / key_already_live 3、概念岗零写入；六项比率在真库可复算（grounding 0.40、evidence 0.9945、referential 1.0、review_lag 23.19h）。过程中修掉四类真问题：`agent_runs` 与另一产品线同名表相撞致 CrashLoop、scout 目录顺序不稳定致重复取用、MinIO 客户端无连接超时把回归挂死、提案去重按提交方而非按主张。**0.x（壹座+永忆执行面）关闭为「推迟」**：windows-admin 公钥全部被拒，另开 change 复跑。**待办：0.1–0.5 待 windows-admin 权限恢复后另开 change 复跑**（草稿已随归档：`runbook-windows-admin.md`）；**2026-11-11 五岗全部生产验证**：巡检派单 / 质检三分类后升级为逐字回源核验 / 取材泵式推进零重复（88 份文档、5142 条单位）/ 结构切条款（民法典 1208、刑法 452、民诉法 306、合同法 428…）/ 概念员只提案（2 块→5 条 pending，可行率 1.0，全部因键已在库被驳回）；接地率 0.293→**0.610**（25/41，含 8 条人工提议+机器验收的策展，3 条被规则拒）；gov 尺子实测一次（104/104，last_run 已落），两线 `gaps []`；**2026-11-11 法律评测补齐**：查实 legal 名下那两条 harbor 尺子（`task_quality`/`trial_behavior`）是基准任务尺子、不评合同，而合同尺子在库里一条都没有（`prompts` 亦为 0）→ 用 `scripts/seed_contract_rubrics.py --domain legal` 落库 86 条 `contract_*`/848 条判据并挂到 legal（生效标准 2→88）；首轮真评 10/10 invalid 暴露判决链结构缺陷（deepeval strict 模板只收 `score`/`reason`，`CONFIDENCE` 自证行进不了判分调用），改为显式 `evaluation_steps` + 定向重问后重跑：complete 5/9、deficient 2/9（缺陷版恰在被删的 `clause_completeness`/`risk_transfer_point`/`defect_warranty` 上翻成 fail），legal `last_run` 已落。**样本是仓内模板填槽草稿而非真实签署合同**，且判官对同一段落摆动过一次（`inspection_period`）——单轮分数不作结论，逐条 `criteria_results` 才是 |
| P1 `add-fleet-execution-loop` | 执行闭环：工单类型化指派人 + 认领/完成、舰队登记与提交方三类来源校验（`fleet:`/`extract:`/`agent:`）、运行台账 `origin`/`runner_ref` 与外部回写、提案结局回流 | P1 | 📝 规划完成（2026-11-13，strict 绿，11 delta：+8 ~3）；基线已实测，未动代码 |
| P1 `add-bench-ops-tools`（paas 仓） | 壹座侧四个 MCP 工具（工单拉取/认领/完成、运行回写）+ pack 接线；凭据按舰队签发 | P1 | 📝 规划完成（strict 绿，+6）；须与上一条同片上产 |
| P2 `add-typed-publications` | 尺子/金集可发布（种类由 pack 注册、digest 复用既有内核）+ 按种类拉取面；本体发布契约零改动 | P2 | 📝 规划完成（strict 绿，+5）；本体与尺子双表并存 |
| P3 `add-domain-next-actions` | 区级「下一步」与总览优先清单、三类空态各自指引、入口可达性、纯读 | P3 | 📝 规划完成（strict 绿，+5 ~1）；依赖 P1/P2 的读面 |

| P1 `add-eval-verdict-ledger` | 评测结论统一台账：subject/ruler 地址 + 四道门闭集 + 三态结局（`inconclusive` 不得冒充）+ baseline 可比性（digest 相等才可比）+ provisional 由校准推导 + 晋升后复测排队 + 机器读面三条只读端点 | P1 | ✅ **已归档上 spec（2026-11-18，19+4 项，全量 2256 绿）**：`eval-verdict-ledger` 新能力 9 需求入库；`bench-platform`/`domain-run-ledger`/`judge-channel-selection` 三处增量。三条线真接上（合同 all-pass / 数据 regression / 判官校准 calibrated）。落地时挖出并修掉两个静默失败（见下条） |
| P1 `fix-ensure-schema-lock-masking` | 建表引导说真话：锁超时不得当成建表成功、就绪只能由实测表存在断言、共享连接跟随 DSN | P1 | ✅ **已归档上 spec（2026-11-18，8 项，全量 2256 绿）**：`schema-bootstrap-liveness` 新能力 3 需求入库。两个缺陷都有「旧代码红/新代码绿」铁证：① `LockNotAvailable` 被吞并标记就绪（并发首启双超时 → 零 DDL 但自称已建表 → 后续写入在远处炸且永不重试）；② `get_shared_conn()` 缓存连接不比对 DSN（运行期切库的进程把 DDL 全打进第一个库）。测试侧连带修掉 CrewAI telemetry 的 `SystemExit(0)` 随机掐断全量会话 |

> 上述四件的顺序、判据与两条岔路的裁决见 `openspec/program.md`（2026-11-13 立）。
