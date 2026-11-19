# Tasks: add-domain-next-actions

> 依赖：`add-fleet-execution-loop`（工单 / 舰队运行）与 `add-typed-publications`（三类发布）的读面先上——否则清单里那几类条目算不出来。
> UI 纪律：动任何页面前先写 surface brief（§0.1），沿 C5 §0.1 的做法。

## 0. 前置

- [ ] 0.1 写 `.impeccable/surfaces/bench-domain-next-actions.md`：Mode = Operate，承接 "The Evidence Ledger"；列管辖页（域总览、我的域、全域矩阵）、Facts 声明（理由里的每个数字都必须能指到来源模块）
- [ ] 0.2 取证：在真库上把「一个域此刻各区实际会给出什么」抄成一张清单（legal + 一个空域各一份），作为实现前的期望基线
- [ ] 0.3 i18n 键骨架：`next_action.*`（按区）、`next_action.empty.*`（三类空态）、`next_action.priority.*`（优先级规则名）zh/en 成对

## 1. 动作投影

- [ ] 1.1 `src/bench/next_actions.py`：`for_domain(conn, domain)` → `{area: {reason, action, entry, priority_key, requires_role} | None}`；九个区各一条判定，全部复用既有查询（`estate` / `quality` / `proposals` / `ledger` / `domain_assets` / 发布）
- [ ] 1.2 判定优先级规则写成显式表 `PRIORITY`（`priority_key` → 名与顺序），顺序须与理由里的严重程度一致；MUST NOT 引入不可解释的加权分数
- [ ] 1.3 同一目标去重：以 `(target_kind, target_key)` 为键去重，两条都指向同一目标时保留优先级高的一条
- [ ] 1.4 `requires_role` 由既有 `_capability()` / 区角色判定给出，不另写权限逻辑
- [ ] 1.5 纯读断言：`for_domain` 内部零写（单测用只读连接跑一遍，断言没有 INSERT/UPDATE 语句被执行）
- [ ] 1.6 `rank(actions)` → 前 5 条 + 其余计数；排序稳定（同优先级按 `priority_key` 字典序，保证两次打开顺序一致）

## 2. 页面

- [ ] 2.1 域总览页顶部：优先清单（≤5 条 + 「还有 N 项」折叠），每条含理由/动作/入口
- [ ] 2.2 各区页顶部：本区的下一动作一条，无待办时明说「这一区没有待办」
- [ ] 2.3 三类空态各自成块：零域、无模板锚、无成员，各有真实入口
- [ ] 2.4 权限不足的条目显示「需要〈角色〉」，不给 403 链接
- [ ] 2.5 我的域列表排序：有事要做的域在前，其次按 `last_opened_at`（不得破坏既有「只列 active 成员域」的语义）
- [ ] 2.6 全域矩阵增下一动作摘要列与「有事要做 / 无事可做」筛选，摘要取自同一投影

## 3. 测试

- [ ] 3.1 每区一条正例：构造该区有缺口的域，断言理由里出现来源模块给出的数字（与模块返回值逐字比对，不硬编期望字符串）
- [ ] 3.2 每区一条空态例：断言返回 `None` 且页面呈现「没有待办」
- [ ] 3.3 优先级：构造同时有复核积压与质量缺口的域，断言顺序符合 `PRIORITY` 表
- [ ] 3.4 去重：两个区指向同一目标，断言清单只有一条
- [ ] 3.5 入口可达：遍历清单里所有 `entry`，断言 `url_for` 能解析（无死路由）
- [ ] 3.6 纯读：打开总览 → 三个区，断言除 `last_opened_at` 外零表变更
- [ ] 3.7 矩阵与总览理由逐字一致（同一域同一区）

## 4. 验收

- [ ] 4.1 浏览器链路：零域身份、空域、有缺口的 legal 各走一遍，截图归档
- [ ] 4.2 一个真域上「按清单从第一条做到最后一条」，确认清单会把做完的项去掉
- [ ] 4.3 全量 `pytest` 绿；`openspec validate add-domain-next-actions --strict` 绿
- [ ] 4.4 `acceptance.md`：逐条判据 + 真库读数

## 5. 挂账

- [ ] 5.1 动作的通知推送（邮件/IM）——本 change 只做页面，不做推送
- [ ] 5.2 跨域的动作优先级（管理员视角该先管哪个域）——矩阵已能筛选，排序规则另议
