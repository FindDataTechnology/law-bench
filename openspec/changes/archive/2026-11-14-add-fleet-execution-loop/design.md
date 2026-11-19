## 基线读数（2026-11-13 实测，生产 `law_bench`，只读）

§0.1 的取证先于设计。读数改了设计里的一处关键假设。

```
domain_proposals 93 行，按 source 分布
  extract:<model>:<prompt_ver>                     78   (84%)  ← 抽取流水线，进程内写
  fleet:fleet_1794335712751_wfa3ww/m_...10rte4      6
  fleet:fleet_1794335712751_wfa3ww/m_...ik4sum      5
  agent:concept@legal / probe / probe2              4          ← 平台自铸身份
  fleet:credential-probe/post_probe                 1          ← 探针，不是真舰队

authoring_tasks     1 行，assignee = agent:concept@legal（内核岗位，非自由文本）
domain_agent_runs  17 行，列确认无 origin / runner_ref
distribution_consumers 2 行：fd-wire(legal) / ontology-fleet-win(legal)
domains            4 个：legal / gov / data-ontology / archive-probe
```

**被推翻的假设**：初稿写「`source` SHALL 解析到一条已登记消费者」。按这条，78 条抽取流水线提案会被全部拒绝，而这正是本域最大的生产者；更糟的是它不区分「进程内调用」与「外部 HTTP 调用」——任何人都能写 `source=extract:任意` 冒充流水线。因此校验改成**按前缀分四类**（见 D6）。

## Context

See `proposal.md` — Why. 只补设计和落地需要、但从动机里看不出来的现状：

- **执行方有两类，机制上已经分层，只是没写下来。** `src/bench/team_roles.py` 的七个岗位全是**确定性 Python**（`run_warden` / `run_verifier` / 取材 / 结构 / 只提案），跑在 bench 进程里，无 LLM。壹座舰队是 LLM 智能体，跑在 dsh runner 上，按 `cron` 节奏起回合。同一个域同时会收到两种产物，而 `domain_agent_runs` 无法区分。
- **身份有两套且互不校验。** bench 认 `agent:<role>@<domain>`（`agent_ids.py`，API key 铸造，禁 `admin`/`*`）；壹座认 fleet / post / cell。提案行上的 `source` 只是被存下来的字符串。
- **唯一的对接线已经存在但只有一个方向。** paas `server/bench-proposal-mcp.js` 的 `bench_proposal_submit`（change `switch-fleet-proposals-to-domain-inbox`，3.1–3.3 已落，3.4/4.x/5.x 未收）。凭据走 `envRefs` 而不是环境变量字面量，因为 dsh 子进程会擦除形似凭据的 env 名（含 `*TOKEN*`）。
- **两个库不是同一个库。** bench 的生产库是 `law_bench`，且已与另一条产品线共库（这就是 `domain_agent_runs` 不能叫 `agent_runs` 的原因）。因此跨方集成只能走 HTTP 契约，不能走共表。
- **既有收敛判据必须保留。** `dispatch` 已按 `target_key` 判「同缺口已有未关闭任务则不重复创建」，`proposals` 已按 `(domain, source, external_key, pending)` 幂等、驳回后同 `evidence_digest` 拒收。新机制只能在它们之上加，不能替换。

## Goals / Non-Goals

**Goals**

- 一条闭环在真库上可判：缺口 → 工单 → 舰队认领 → 执行 → 运行回写 → 产物入箱 → 确认/驳回 → 结果回流。
- 两类执行方在同一页上可辨：值班长能一眼看出「这一轮是内核跑的，还是舰队跑的，哪个舰队哪一轮」。
- 身份从注释变成事实：三处（提案、工单、运行回写）的来源都经同一条校验，同一个登记记录。
- 内核七岗的行为与既有 spec 语义零回归。

**Non-Goals**

- 不做调度：知验台不决定舰队何时跑，工单只表示「有待办」，认领由舰队自己的节奏驱动。
- 不做共库、不做反向 RPC、不做知验台向壹座推送任务（拉取，不推送）。
- 不改 `domain_proposal_events` 与 `authoring_events` 的 append-only 性质。
- 不在本 change 做三类发布（那是 `add-typed-publications`）、不做控制台改版（那是 `optimize-domain-console`）；本 change 只提供读面所需的事实。

## Decisions

### D1 工单不新建表，`authoring_tasks` 升格

`authoring_tasks` 已经有 `status` 四态、`transitions` JSONB、`target_kind/target_key` 与幂等收敛判据，认领/完成正好是它缺的那两个转移。新建 `work_orders` 表会立刻出现「同一缺口两张单、两套状态机」，而这正是本 change 要消灭的东西。

代价：`assignee` 一列承载三种语义。用 `assignee_kind`（`human` / `kernel-role` / `fleet`）+ `assignee_ref` 两列把它挑明，`assignee` 保留为人读展示名，避免改所有既有读点。

**Alternatives considered**：① 新表 `work_orders` —— 否决，双状态机；② 只加 `assignee_kind` 不改 `assignee` 语义 —— 否决，`assignee` 同时是 `mine = task["assignee"] in {sub,email,name}` 的判据，混用会让授权判断依赖类型。

### D2 舰队登记复用 `distribution_consumers`，不建第二张登记表

`distribution_consumers` 已有 `name`（唯一）、`domains[]`、`token_hash`（唯一）、`revoked_at`，正是「谁、能碰哪些域、凭据、是否失效」这四件事。加 `kind`（`machine` / `fleet`）与 `fleet_ref` 即可。

关键取舍：**一个舰队一条登记、凭据按舰队签发**，不按岗位签发。理由：岗位是 pack 里的声明，会随 pack 版本与岗位增删变化；舰队是平台侧的实体，`source=fleet:<fleet_id>/<post_id>` 里的 `fleet_id` 才是稳定键。按岗位签发会把凭据生命周期绑在易变对象上。

**Alternatives considered**：① 新表 `fleet_registrations` —— 否决，两张表都要回答「能碰哪些域」，必然漂移；② 沿用 `agent:<role>@<domain>` 由舰队自报 —— 否决，自报身份等于没有身份。

### D3 运行台账同表分列，不建第二本账

`domain_agent_runs` 加 `origin`（`kernel` / `fleet`）与 `runner_ref`（`fleet:<id>/<post>#<round>`）。同表的价值是四态、进度不变量、`counts` 口径全部**共用一份判定代码**；两本账会让「`thin` 要不要升级给人」这类判定出现两套实现。

外部回写用 `run_key` 幂等：`run_key = runner_ref`，重放不新增行（`guard` 在 `agent_runs.start` 已有的 `run_key` 语义上扩展为唯一约束或等价的存在性检查）。**必须选存在性检查，而不是靠唯一索引去判断**：`run_key` 允许为空（内核岗位有用例不传），Postgres 的 `UNIQUE` 对 NULL 不去重，一个覆盖全表的唯一索引会给出「看起来防住了其实没防」的安全感。

实施时补了一道**部分**唯一索引（`WHERE runner_ref IS NOT NULL`）作兜底：存在性检查与插入之间有 TOCTOU 窗口，两个重试可以同时查不到、同时插入，台账就会写下「同一轮完成两次」。部分索引只约束那个必须唯一的域（外部回写），内核的 null 行一行都不受影响——所以它不是替代，是兜底。撞上它时回读既有行、照旧报「已存在」（`created=False`），不把冲突抛给调用方当故障去重试。

**Alternatives considered**：① 建 `fleet_runs` 表 —— 否决，判定逻辑分叉；② 回写时直接 `INSERT` 依赖调用方不重放 —— 否决，网络重试是常态。

### D4 分诊规则进代码，不进提示词

「确定性活归内核、需判断的活归舰队」写成 `dispatch.GAP_ROUTE`（缺口 → `kernel:<role>` 或 `fleet`），而不是写在岗位提示词里让 LLM 自己判断。理由：提示词是建议，代码是约束；写进提示词等于把一个可判定的规则变成概率。

`GAP_OWNER` 保留原值作为 `kernel` 一档的实现，`GAP_ROUTE` 是它的超集。缺口词表以外的值仍按既有行为报 `ValueError`。

### D5 `source` 收紧是有意的破坏性变更，配一次性迁移通道

收紧后未登记来源 403。为了不让在跑的舰队静默断掉，提供 `scripts/register_fleet.py --from-observed`：从既有 `domain_proposals.source` 里枚举出 `fleet:*` 形态的去重值，dry-run 输出计数与建议的 `fleet_ref`，由人确认后写登记。

实测存量只有 12 条 `fleet:*`（含 1 条 `credential-probe` 探针），确认成本很低。

**不做自动登记**：自动把观察到的字符串变成登记，等于把「来源是事实」换成「来源是曾经出现过的东西」，那和现在没有区别。探针来源正是靠人工确认才能被识别出来的那一类。

### D6 四类来源，四种可信依据——不能压成一条规则

实测把初稿的一处设计错误暴露出来：`extract:*` 占 93 条提案的 84%，而它是**进程内**写的（`src/bench/extraction.py:796`），没有凭据可验。若沿用「查登记表」的统一规则，要么拒掉全部流水线产物，要么给 `extract:` 开一条谁都能命中的口子。

因此校验按前缀分四类，各用各自的可信依据：

| 类别 | 可信依据 | 外部 HTTP | 进程内 |
|---|---|---|---|
| `fleet:<id>/<post>` | 已登记、未吊销、绑定本域的舰队 + 凭据 | 允许 | 允许 |
| `extract:<model>:<ver>` | **调用位置本身**（不在 HTTP 面上） | **拒绝** | 允许 |
| `agent:<role>@<domain>` | 平台已铸身份 + 域活跃成员 | 允许 | 允许 |
| `user:<identity>` | 已认证会话（拿不出可比身份即不匹配） | 允许 | 允许 |

关键取舍：`extract:` 的可信依据是「这段代码不在网络面上」，因此**外部提交端点对 `extract:` 一律拒绝**——这不是配置项，是安全边界。放宽它等于允许任何人自报为流水线。

### D7 闭环必须由机器通道闭合，不能靠会话

实施到「舰队领单」这一步才发现初稿漏了一整段：会话路由的授权判据是「这张单是不是派给**我**的」，而 `kernel-role` / `fleet` 两档的指派对象都不是一个登录的人，于是 `mine=False`，只有域负责人能动。那**不是**舰队在认领，是有人替它点了按钮。

后果不是报错，是**一句话变成谎话**：界面上写着「等待舰队认领」，而这件事永远不会发生。这正是本 change 要拆的那类「看着闭合其实没接」。

因此补三个机器写面，与拉取面共用同一枚 `X-Consumer-Token` 与同一条 `submitters.may_read_runner_ref` 隔离判据：

| 端点 | 谁可以调 | 拒绝形态 |
|---|---|---|
| `POST /api/v1/distribution/{key}/work-orders/{id}/claim` | 该单派的舰队 | 重复认领 409；不是派给它的 403 |
| `POST .../complete` | 同上 | 未认领 409；写坏 JSON 422（空体合法） |
| `POST /api/v1/distribution/{key}/runs` | 同上，且 `runner_ref` 必须是自己的前缀 | 别人的 ref 403；结局出词表 422 |

授权一律读 `assignee_kind` + `assignee_ref`，**不读显示名**：两支舰队可以把名字都叫 `ontology-fleet`，只有登记引用能分清谁被派了活。

**实施后补记（同一条原则漏了最后一格）**：上面三个写面让舰队能领单、能执行、能报数，但**产物**只能从会话面提交——而会话要求一个能代表人的凭据，正是本节否决的形态。于是「闭环」在最后一格上仍然需要一个人，只是那一步被写成了测试里的 `svc-fleet` 服务账号，看起来像闭合。补两个面之后它才真的闭：

| 端点 | 谁可以调 | 拒绝形态 |
|---|---|---|
| `POST /api/v1/distribution/{key}/proposals` | 舰队以**自己**的来源提交 | 别人的前缀 / `extract:` / `agent:` / `user:` 403；重放 `created:false` |
| `GET /api/v1/distribution/{key}/proposals/outcomes?source=` | 同上，读自己来源的结局 | 别人的前缀 403（**不是空列表**——空列表读作「什么都没发生」） |

`submitted_by` 由来源派生，不取请求体：机器只有一个身份。确认仍只有会话面，所以自提自确认在机器道上**不可能**发生，而不是靠两个人绕过去。

**Alternatives considered**：① 让舰队用一个「服务账号会话」登录 —— 否决，那要求舰队持有一个能代表人的凭据，反而把「人」与「机器」的边界抹掉；② 由域负责人代为认领 —— 否决，代认领会让「认领时间」不再等于「执行方开始的时间」，台账的时序从此不可信；③ 让舰队用服务账号会话提交产物 —— 同样否决，理由同 ①，而且是同一个漏洞的第二种写法。

### D8 提交与复核必须是两个身份

闭环端到端跑第一遍时被自提自确认闸拦下（`提案人不得自提自确认`）。这不是障碍，是判据：fleet 侧用服务身份提交、域负责人复核，两道身份各是各的闸。测试里因此显式建了 `svc-fleet`（expert）与 `lara`（lead）两个成员；若沿用同一个身份，闭环**不应该**通过。

**Alternatives considered**：① 给流水线也发一条登记与 token —— 否决，进程内调用加凭据只是把「不可伪造的位置」降级成「可泄露的秘密」；② 只校验 `fleet:`、其余放行 —— 否决，`agent:` 前缀受自提自确认禁令保护，自报该前缀会让禁令在错误身份上生效（见 `agent_ids.py` 的设计说明）。

## Risks / Trade-offs

- [收紧 `source` 会让在跑的舰队被拒] → 先跑 dry-run 迁移；切换窗口内 `BENCH_PROPOSAL_STRICT_SOURCE=0` 保留一档宽松（记录 `legacy` 计数），观察一轮后翻硬。
- [工单与派单并存造成两张单] → 工单必须由 `dispatch.dispatch()` 创建，路由层不再有第二条 `authoring_create_task` 调用点；测试断言「路由层零直接调用」。
- [外部回写的 `counts` 口径与内核不一致，让「六项质量比」不可比] → 回写只写 `counts` 与 `artifact_refs`，比率仍由 `domain_quality_metrics` 从库重算；回写值只进台账展示，不进比率分子分母。
- [`assignee` 保留人读名会让授权判断拿到展示名] → 授权统一改读 `assignee_kind` + `assignee_ref`；`mine = assignee in {sub,email,name}` 只在 `assignee_kind='human'` 分支保留。
- [同表分列后，team 页排序把两类混在一起] → 排序键改为 `started_at DESC`，`origin` 只作分列与筛选，不参与排序（否则「最新一轮」会被某一类垄断）。
- [`via` 参数传错即等于没有校验] → `extract:` 的放行**只依赖** `via="in_process"` 这一个值；两个调用点各传常量（HTTP 路由传 `"http"`、内部端点传 `"in_process"`），并有一条测试**从真实 HTTP 路由**发 `source=extract:...` 断言 403——测的是路由，不是函数。
- [抽取流水线改造后忘了传 `in_process`] → 症状是该域抽取产物全部 403 且不入箱；测试覆盖「进程内路径放行」，回归即红。
- [迁移期既有 `domain_proposals.source` 里存在无法对应任何舰队的历史值] → 归入 `legacy` 保留可读，不参与校验、不阻断读面；`legacy` 行的数量进迁移报告。

## Migration Plan

实测存量很小，迁移可以一次做完并有明确的零判据。

1. **加列（幂等）**：`ensure_schema` 增 `authoring_tasks.assignee_kind/assignee_ref`、`distribution_consumers.kind/fleet_ref`、`domain_agent_runs.origin/runner_ref`，全部带 `DEFAULT` 使存量行可读（`assignee_kind='human'`、`kind='machine'`、`origin='kernel'`）。
2. **回填**：`scripts/backfill_assignee_kind.py` 按 `GAP_ROUTE` 把既有派单行归类。实测只有 1 行（`agent:concept@legal`），归 `kernel-role`。
3. **登记**：`scripts/register_fleet.py --from-observed` dry-run → 人确认 → `--apply`。实测待登记 2 个 fleet id + 1 条探针（探针应显式不登记，走 legacy）。**既有的 `machine` 登记是原地升级，不是重登记**：产库 `ontology-fleet-win` 就是一条真舰队的老登记，而 `register_consumer` 只新建（撞 `name`/`token_hash` 两条唯一约束），吊销重登记又会换掉 token、把在跑的舰队切断。所以脚本拿到一枚**已在库里的** token 时走 `distribution.promote_consumer_to_fleet`：只改 `kind`/`fleet_ref`，`id`/`name`/`token_hash`/`domains` 一个字不动，客户端无感。改名、改域、或那枚 token 属于另一条登记，一律拒绝并说明下一步（域要改加 `--set-domains`）。
4. **翻校验**：先 `lenient`（记 legacy），跑一轮真实提交与回写，确认 `legacy` 计数为 0 后翻 `strict`。注意即使 `lenient`，外部提交 `extract:*` 也拒绝（D6）。
5. **回退**：把校验档位切回 `lenient`（一行配置），不动数据；列保留不影响读。

### 上线顺序（实施后补记，含环境变量与观测点）

默认档是 `strict`，而产库有 12 条历史 `fleet:` 来源。**镜像一落地就 strict，等于把正在跑的舰队当场切断**——这正是 `register_fleet.py` 存在的理由。所以上线只有两条安全路径：

**路径 A（推荐）：先登记，再 strict。**
1. 对新镜像起一次 boot（任意一次性 Job 即可），确认六列 + 部分唯一索引就位、存量行取到默认值。
2. `register_fleet.py --from-observed` → 人确认 → `--apply`（需该舰队**现有** token）。产库那条已存在的 `ontology-fleet-win` 会被**原地升级**（`machine → fleet`，token 不变），不会因为名字已存在而失败。
3. `--legacy` 的「现在再提交会被拒」清单里只剩历史行（探针、旧错配）→ 滚新镜像，不设 `BENCH_SUBMITTER_MODE`。

**路径 B：先 lenient，再收窗。**
1. 滚新镜像时在清单里加 `BENCH_SUBMITTER_MODE=lenient`（`_submitter_mode()` 每次调用读环境，所以这是唯一开关，不需要改代码）。
2. 跑一轮真实提交：`GET /api/v1/distribution/legacy-sources` 看 `mode: lenient` 与新增组。
3. 完成登记后，去掉该环境变量并重启 → 默认即 `strict`。
4. 收窗判据：`--legacy` 的「会被拒」清单里**没有仍在提交的来源**。不是「计数为 0」——历史行不会消失。

**回退**：设回 `lenient`（只改环境，不动数据）；或回滚镜像——列是加法，旧代码忽略它们，新写入的行仍带 `submitter_verdict`，回滚后读面照常。

**观测点（三条，都可只读核对）**：六列 + 索引存在且存量行非空默认值；`legacy-sources` 的 `mode` 与实际档位一致；一次真提交返回 200 并带 `created`。

