# tasks.md — add-web-human-review

## 1. Schema 与存储层

- [x] 1.1 `src/eval/store.py`：新增 `REVIEW_TASKS_SCHEMA` 常量并纳入 `ensure_schema` 自愈路径（`CREATE TABLE IF NOT EXISTS review_tasks`，含 `eval_criteria_result_id` 外键级联）
- [x] 1.2 新建 `src/eval/review.py`：`create_batch`（幂等）、`list_batches`/`batch_stats`、`list_tasks`（按批次/状态/标注员过滤）、`get_task_detail`（join `eval_criteria_results`/`eval_runs`/`rubrics`/`criteria`，validity 不取模型判定列）、`decide_task`（条件更新，返回冲突信息）
- [x] 1.3 `tests/test_review_store.py`：批次幂等、级联删除、盲评 detail 不含模型判定、双人槽位隔离、条件更新冲突

## 2. Web 路由与模板

- [x] 2.1 新建 `src/web/routes/review.py`：`GET /review`（批次与任务列表，read 路由）、`GET /review/{task_id}`（决策表单，read 路由）、`POST /review/{task_id}/decide`（write 路由 + `require_scope("review:annotate")`，annotator 取会话身份）
- [x] 2.2 模板 `review_list.html` 与 `review_task.html`：继承 `base.html`；validity 表单只有 pass/fail + 备注，gold_curation 表单展示模型判定与理由 + approve/reject/skip；冲突与 flash 消息
- [x] 2.3 `base.html` 导航加 `/review` 入口；路由模块注册进 `src/web/app.py`
- [x] 2.4 `tests/test_review_web.py`：匿名重定向登录、无 scope 决策 403、盲评页面不含模型判定、正常决策流转、二次提交冲突

## 3. 抽样与导出脚本

- [x] 3.1 `scripts/finetune/web_review_seed.py`：`--list-runs`（按 rubric/时间列出候选运行）与抽样建批（`--batch-id/--types/--run-ids/--per-type/--annotators/--batch-type`），幂等
- [x] 3.2 `scripts/finetune/web_review_export.py`：统计（每人决策数、双人吻合率与 κ、人-判官一致率）+ 污染告警（`--judge-agreement-warn` 默认 0.98）+ gold 导出（`reviewer=human` 溯源，legal_base 缺失计数）
- [x] 3.3 `tests/test_review_export.py`：κ 计算、污染告警触发、导出溯源字段

## 4. 验证与运维

- [x] 4.1 本地 Docker 起 Postgres（15432），全量跑新增测试与受影响的既有测试（`test_review_*`、`test_app.py`），全部通过 —— 新增 32 项 + `test_app.py` 共 35 项全绿；全量套件 718 passed / 23 failed，23 项经逐条核对均为既有失败（合同类型集漂移、脚本已移入 `scripts/archive/`、缺 `llama_index`/`crewai` 可选依赖、槽位本体漂移），与本次改动无关
- [x] 4.2 `openspec validate add-web-human-review` 通过；手工验收清单写入 change 目录（`ops-checklist.md`：Logto 建 `lawbench-annotator` 角色与 `review:annotate` scope 的运维步骤、`LOGTO_SCOPES` 追加与 `AUTH_ADMITTED_SCOPES` 两种方案、抽样→标注→导出的操作顺序、9 项手工验收勾选表、回滚）；配套把新 scope 与角色补进 `deploy/cheap-box/web-rbac-logto.md`、把 2d) 流程补进 `docs/finetune-data.md`；另以真实 CLI 在本地库跑通「建批 → 双人标注 → 统计/导出」全流程（κ=0.400、人-判官一致率 0.833）
