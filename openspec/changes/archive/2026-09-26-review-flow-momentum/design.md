# Design: review-flow-momentum

## Context

现状（`src/web/routes/review.py` + `src/web/templates/review_task.html`）：`review_decide` 成功后 303 回 `/review` 列表；判定表单是普通 `btn`；无任何键盘支持；无进度信息。`src/eval/review.py` 已有 `list_tasks(batch_id, status, for_annotator, db)` 返回按槽位排序的任务字典列表——next-task 与位置计算都不需要新的存储层代码。

## Goals / Non-Goals

- Goals：判定循环里少两次导航；不可逆动作有视觉分量；高频动作可键盘完成。
- Non-Goals：不做批量判定、不做判定撤销（撤销与并发安全另行立项）、不做 review 页面的 i18n 迁移（独立变更，见 `web-i18n`）、不改 `decide_task` 的存储与并发语义。

## Decisions

### D1: next-task 重定向在 route 内查询，不新增 store API

`review_decide` 成功后用现有 `list_tasks(batch_id=task.batch_id, status="pending", for_annotator=_annotator_of(user), db=db)` 取同批次自己的待判队列：非空则 303 到 `/review/{tasks[0]["id"]}`，空则 303 到 `/review?batch=...`。查询发生在决策落库之后，只读，不影响冲突路径（冲突在 `outcome["ok"]` 为假时提前返回，不触达 next-task 查询）。

flash 分两条约定：成功提示走 base.html 既有的 `?msg=` 查询参数（渲染为 ok 样式，未收录文案原样透传）；冲突提示保持 review 页自己的 `?flash=` error 约定不变。

### D2: 位置指示在 `review_task` route 内计算

`get_task_detail` 返回后，同样用 `list_tasks(for_annotator=当前登录身份)` 取该批次待判 id 列表，模板拿到 `pending_ids` 后计算 `k = index(task.id)+1`、`n = len`。任务已判定（revisit）时不传该上下文，模板省略指示。注意：`for_annotator` 语义是「排他锁定给该标注员的队列」，与 decide 后的重定向使用同一队列口径，数字自洽。

### D3: 数字键只选中、不提交

`review_task.html` 底部加一小段原生 JS（无框架依赖，与 app.js 同风格）：`keydown` 监听，`1..n` 按渲染顺序选中对应 radio；`event.target` 为 `textarea/input` 或带修饰键时忽略。label 上渲染「按 1」提示。不自动提交：不可逆动作必须显式确认（按钮或 Enter 原生提交），这是有意的保守取舍——省一次点击不值得冒险误判入库。

### D4: 样式只动两处

提交按钮 `btn` → `btn-primary`（DESIGN.md：每页一个主按钮，判定页此前没有主按钮，不冲突）。进度行复用 `.muted .small`。不改色板、不加组件。

## Risks / Trade-offs

- `list_tasks` 在每次判定后多一次只读查询——单人操作场景，量级可忽略。
- 数字键映射依赖 `allowed_verdicts` 渲染顺序（validity 2 键 / gold_curation 3 键），顺序来自 `_verdicts_for` 的硬编码元组，稳定。
- 键盘监听对屏幕阅读器用户无影响（radio 本身原生可聚焦操作），提示文字是渐进增强。

## Migration Plan

纯增量：无 schema 变更、无数据迁移、无 API 变更。部署即生效。

## Open Questions

无。
