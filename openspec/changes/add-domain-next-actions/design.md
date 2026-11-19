## Context

见 `proposal.md` — Why。设计相关的现状：

- 判定逻辑已经全部存在，且各自有唯一口径：`src/bench/estate.py` 的缺口矩阵与六项质量比、`src/bench/quality.py` 的比率算法（分子分母可复算）、`src/bench/proposals.py` 的待确认计数与最老年龄、`src/bench/ledger.py` 的四层台账、`add-fleet-execution-loop` 的工单状态、`add-typed-publications` 的发布状态。
- 区可见性由 `src/web/domain_context.py` 的 `visible_areas` 与 `_capability()` 计算，路由各自独立判权限（C5 §1.7 建立的双闸）。
- 一条既有约束：打开域时写 `domain_members.last_opened_at`（`touch_last_opened`）。这是本能力唯一被允许的写。

## Goals / Non-Goals

**Goals**
- 每区的下一动作只用既有查询结果，不新增任何口径。
- 总览的清单顺序可解释：用户能看出为什么这条在前面。
- 三类空态各自指到一个真实、当前账号能打开的入口。

**Non-Goals**
- 不做跨域排序（哪个域该先管）。
- 不做通知/推送。
- 不改任何区的判定逻辑。

## Decisions

### D1 下一动作是「投影」，不是「计算」

`next_actions.for_domain()` 只读取既有模块的返回值，把「缺口 + 比率 + 计数 + 状态」翻译成 `(reason, action, entry, priority_key, requires_role)`。任何需要新算的数都不许在这里算——一旦在这里算，同一件事就有两处口径，而界面上显示的和模块返回的会分叉。

判据靠测试钉住：断言 `reason` 里出现的数字与来源模块的返回值**逐字相同**（不是硬编期望字符串）。

### D2 优先级是显式表，不是加权分数

```python
PRIORITY = (          # 顺序即优先级
  "review_backlog",   # 有人在等确认 —— 唯一会阻塞他人的
  "quality_below_floor",
  "pillar_empty",
  "work_order_open",
  "publication_stale",
)
```

理由：加权分数不可解释，用户无法判断「为什么复核排在质量后面」；而这张表本身就是可以在界面上原样呈现的解释。表外的键即报错，避免有人加了一条动作却忘了给它排序位置。

**替代方案**：按区导航顺序 —— 否决，导航顺序是信息架构，不是urgency。

### D3 去重按目标键，不按动作文案

不同区可能指向同一件事（例如「复核积压」与「提案箱待确认」都指向同一批提案）。去重键是 `(target_kind, target_key)`，保留优先级高的一条。不能按文案去重——文案是模板，可翻译、可改，用它做键会在 i18n 时静默失效。

### D4 入口可达性由 `requires_role` + `url_for` 双重保证

每条动作带 `requires_role`（来自既有 `_capability()`，不另写权限逻辑）。渲染时：当前账号满足 → 给链接；不满足 → 给「需要〈角色〉」文案，不给链接。测试遍历所有 `entry`，断言 `url_for` 能解析，杜绝死路由。

### D5 清单硬上限 5 条，其余折叠

不限上限会让一个烂域变成一屏十条「你应该做」，此时用户的选择是全部忽略。硬上限 + 「还有 N 项」保留可展开性，也不隐藏事实。

## Risks / Trade-offs

- [下一动作算得过于积极，变成噪音] → 硬上限 + 优先级表 + 每区只有一条（不是每区三条）。
- [理由里的数字与模块返回值漂移] → 测试逐字比对；不在 `next_actions` 里做任何格式化算术（除法、四舍五入都由来源模块给）。
- [`requires_role` 与路由的实际权限判定分叉] → 两处都读 `_capability()`；另有一条测试对每个区断言「requires_role 判定为可见的账号，真请求该入口不是 403」。
- [纯读承诺被后续改动破坏] → 测试用只读连接跑 `for_domain`，并在浏览器链路里断言除 `last_opened_at` 外零变更。

## Migration Plan

1. `next_actions.py` 先只接两个区（评测、提案）并上页面，观察一轮清单是否可用。
2. 补齐其余区；每补一个区加一条正例 + 一条空态例。
3. 全域矩阵接同一投影（不另算）。
4. 回退：总览清单区可整体隐藏（配置位），各区页顶部的单条动作独立渲染，互不依赖。
