# Tasks: review-flow-momentum

## 1. 路由层（src/web/routes/review.py）

- [x] 1.1 `review_decide` 成功路径：决策落库后用 `review_store.list_tasks(batch_id=task.batch_id, status="pending", for_annotator=_annotator_of(user), db=db)` 取同批次自己的待判队列；非空 303 → `/review/{first.id}?flash=已记录判定，继续下一条`，空 303 → `/review?batch={batch_id}&flash=本批次待判已清空`。冲突路径（`outcome["ok"]` 为假）保持现状不动。
- [x] 1.2 `review_task`：`get_task_detail` 成功且 `task["status"] == "pending"` 时，同样取该标注员的待判 id 列表，传入模板上下文 `pending_ids`（列表内含当前 task.id；若无则不传或传空）。

## 2. 模板层（src/web/templates/review_task.html）

- [x] 2.1 队列位置：`pending_ids` 非空且含当前 id 时，在元信息行渲染「第 k / n 条待判」；已判定任务不渲染。
- [x] 2.2 提交按钮改 `btn-primary`，「提交后记录你的登录身份，不可修改」提示保持在按钮旁。
- [x] 2.3 每个判定 label 渲染「按 {序号}」提示（`loop.index`）。
- [x] 2.4 页面底部加原生 JS：`keydown` 监听数字键 1..n 按渲染顺序选中对应 radio；`event.target` 是 `input/textarea/select` 或 `event.altKey/ctrlKey/metaKey` 时忽略；只选中不提交。

## 3. 测试（tests/test_review_web.py）

- [x] 3.1 判定成功且同批次还有待判：断言 303 目标是下一条 `/review/{id}` 且 flash 携带成功文案。
- [x] 3.2 判定成功且队列清空：断言 303 目标是 `/review?batch=...` 且 flash 提示清空。
- [x] 3.3 冲突路径回归：并发占先的 decide 仍重定向回当前任务并带冲突 flash。
- [x] 3.4 pending 任务页面包含「第 k / n 条待判」与 `btn-primary`；decided 任务页面不含位置指示。

## 4. 验证

- [x] 4.1 本地起 preview（`.impeccable/preview_app.py`），用种子 review_tasks 走一条完整判定链：位置指示 → 数字键选中 → 提交 → 自动落到下一条 → 清空后回列表。
- [x] 4.2 `openspec validate review-flow-momentum` 通过；detector 对改动的模板无新增真实告警。
