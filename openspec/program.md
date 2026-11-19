# 知验台 ↔ 壹座 执行闭环 · 程序总纲

> 状态：2026-11-13 立。四个 change 的规划已落盘并过 `openspec validate --strict`，尚未动一行实现代码。
> 定位：本档只定**顺序、判据与界线**。每一件「怎么做」在各自 change 的 `design.md` 里，不在这里复述。

## 一、一句话目标

让壹座的舰队成为知验台的**执行方**而不只是提交方：知验台派单 → 舰队领单 → 跑完回写 → 产物入提案箱 → 确认或驳回 → 结果回流。这条环上今天只存在最后一跳的一半。

## 二、事实基线（都有出处，不是判断）

**已经通的四条**

| 连接 | 落点 | 证据 |
|---|---|---|
| 共享身份 | Logto（bench 认 scope、壹座认 group） | 本仓 `src/web/auth/scopes.py` |
| 工具面 | law-bench 远程 MCP 对 `legal` / `hpe07qejcwk7` 两组可见 | `fd-infra-deploy/all-services/prod/platform.yaml` 的 `registry-groups.json` |
| 提案单向 | 壹座 `bench_proposal_submit` → `POST /api/d/{key}/proposals` | `paas/server/bench-proposal-mcp.js`；change `switch-fleet-proposals-to-domain-inbox` 3.1–3.3 |
| 官网门面 | 官网 → `lawbench.finddatatech.cloud/d` | `fd-official-web/src/content/apps/zh/zhiyantai.md` |

**还缺的五条**

| 缺口 | 现状（出处） |
|---|---|
| 派单是死胡同 | `src/bench/dispatch.py` 的 `GAP_OWNER` 只含内核七岗；模块自述「Nothing here decides *who*」；`authoring_tasks.assignee` 是自由文本 |
| 运行台账半盲 | `domain_agent_runs` 无 `origin` / `runner_ref` 列（`src/bench/workspace_store.py`），而 `/d/{key}/team` 正是查它 |
| 驳回不回流 | 理由只在 `domain_proposal_events`，无提交方读面 |
| 身份是注释 | `source=fleet:<id>/<post>` 无人校验；`distribution_consumers` 无 `kind` |
| 尺子出不去 | 蓝图 §六 承诺三类可发布，`publish_domain()` 只做本体；`domain_rubrics` 无版本无 digest |

## 三、分工界线（本程序的全部立论）

```
确定性、可机械判定            →  知验台内核七岗（Python，跑在 bench 进程内）
需要判断、要 LLM             →  壹座舰队（dsh runner，按 cron 起回合）
人签字                       →  域负责人（确认 / 发布 / 指派）
```

这条线今天**不存在**，后果是同一条缺口两个执行方都会去干、产物进同一个箱、两本账各记一半。`domain-work-order` 的 `GAP_ROUTE` 就是它落成代码的地方。

## 四、四个 change 与顺序

```
 P0 收口            P1 闭环               P2 互用              P3 优化
 ─────────         ─────────            ─────────            ─────────
 paas 既有 change   bench                bench                bench
  3.4/4.x/5.x        add-fleet-           add-typed-           add-domain-
                     execution-loop       publications         next-actions
                        ↑ 并行
                     paas
                       add-bench-ops-tools
```

### P0 · 收口（无新 change，把在途的跑完）

`paas/openspec/changes/switch-fleet-proposals-to-domain-inbox` 的剩余任务：3.4（本轮报告字段）、4.1–4.4（契约与纪律测试）、5.1（validate）、5.2（**一轮真跑两侧对照**）、5.3（真确认一跳）。

**为什么排第一**：P1 的所有判据都要靠这条已通的桥供料。桥修好了但没跑过车，「两侧对照」这件事至今没有一次实证。

**判据**：一轮真跑后知验台域提案箱 +N；柏讯 `domain_action_instances` 本体类 +0（对 2026-11-08 基线 11 条）；同键重复提交幂等；域负责人确认后 `knowledge_units` 出现该键且有 `authoring_events`。

### P1 · 闭环（本程序的核心）

- **bench `add-fleet-execution-loop`**：工单类型化指派人 + 认领/完成、舰队登记与来源校验、运行台账 `origin`/`runner_ref` 与外部回写、提案结局回流。两个新能力（`domain-work-order`、`fleet-submitter-contract`），三个修改（`domain-run-ledger`、`knowledge-distribution`、`domain-estate-console`）。
- **paas `add-bench-ops-tools`**：一个 stdio MCP 模块四个工具（`bench_work_order_list/claim/complete`、`bench_run_report`）+ pack 接线。

两侧**必须同片上产**：客户端遇到对端 404 必须报「该面未上线」，不得返回空列表（`bench-ops-tools` 的既有要求）。

**判据（一条链，四份证据）**：真缺口 → 派给舰队 → 舰队领单 → 回写运行 → 提交提案 → 负责人确认 → `knowledge_units` 出现该键。工单行、运行行（`origin=fleet`）、提案行、单元行四份都在，且团队页同屏可见两类运行。

### P2 · 互用

**bench `add-typed-publications`**：尺子与金集可发布（种类由 pack 注册，digest 复用既有内核），按种类拉取面，发布页列三类。**本体发布契约一行不改**——wire 正在生产上拉 `digest 5897354d`，重算或搬表会作废已发出的账。

**判据**：legal 发布一版 `rubric`，已登记消费者拉到并比对 digest；本体五条既有场景（发布/幂等/空域拒/换底 digest/形状拒）全绿。

### P3 · 优化

**bench `add-domain-next-actions`**：每区算「下一步」，总览聚成 ≤5 条的优先清单，三类空态各有指引，入口可达性校验，纯读。

**为什么最后**：清单里会有「有舰队工单等着看结果」「尺子还没发布过」这类条目——它们要 P1/P2 的读面才能算出来。先做等于做两遍。

**判据**：零域 / 无模板锚 / 有缺口三种情形各走一遍；真域上「按清单从第一条做到最后一条」，做完的项从清单消失。

## 五、两条岔路的裁决（已定，理由是硬约束不是偏好）

### D1 派单通道走 paas 侧 stdio 客户端，不走知验台现成的 MCP HTTP 端点

知验台**确实已有一个** streamable-HTTP MCP（`<box>:30840/mcp`，`MCP_HTTP_TOKEN`，注册在 AI 网关、非公开、仅 admin 组）。不选它的理由：

1. **单 token 无归属**：54 个工具共用一个 token，回写进去的运行记录证明不了是哪个舰队干的——而归因正是这次要修的东西。
2. **工具面过宽**：一次给岗位装 54 个工具，其中含写面，远大于它的职责。

代价是 paas 侧多一个模块；换来凭据按舰队签发、工具面按岗位裁剪、错误语义与既有提案工具完全一致。

### D2 「域模板打成 pack 上谦面市场」本版不做

它会把知验台从「评测与本体工作台」变成「可安装的域产品」，是另一次产品化，且必须与 `fleet-packs/blueprints/ontology-builder` 对齐——否则就是第二份团队模具（见既有教训：`fleet-is-the-team-pack-is-the-mold`）。

**本版只做到「尺子与本体可以被已登记的消费方拉走」**。域模板成包留待单独裁决。

## 六、明确不在本版做

- 知验台直接调度壹座（推任务而非等认领）——派单只到工单，执行节奏归舰队。
- 知验台与壹座共库——松耦合铁律，两者之间只有 HTTP 契约。
- 把 `ontology_publications` 统一进新表——会作废已发布的 digest。
- 客户登录 UI / 消费者反向写回（蓝图 D9 早已明确不做）。
- RAG 语料发布（蓝图三类的第三类）——语料有独立生命周期与体积问题，另立。

## 七、验证纪律（本程序特有的三条）

1. **判据必须落在真库/真请求**：工单、运行、提案、单元四份证据都要能在库里查到行；不接受「界面显示了」。
2. **两侧同片**：跨仓集成必须在一轮真跑里同时观察两端；单侧期望是自己写的等于伪证。
3. **对端缺席必须报错**：任何「对端 404/未上线」一律报错，不许返回空清单或空成功——这是本类集成最容易产生的静默假绿。

## 八、风险摘要

| 风险 | 处置 |
|---|---|
| `source` 收紧（BREAKING）让在跑的舰队被拒 | 先 `register_fleet.py --from-observed` dry-run 登记；切换期留 `legacy` 宽松档并计数，翻硬前须计数为 0 |
| 工单与既有派单并存出两张单 | 工单只能由 `dispatch.dispatch()` 创建；测试断言路由层零直接调用 |
| 外部回写污染质量比 | 回写只进台账展示，比率仍从库内内容重算 |
| 下一动作算成一屏十条 | 硬上限 5 条 + 折叠 + 优先级规则可读 |
| 两侧不同片造成假空 | 客户端对 404 强制报错，并有一条专门的测试 |
