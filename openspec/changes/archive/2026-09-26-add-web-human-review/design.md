# design.md — add-web-human-review

## Context

人工审查现有链路是本地文件流（`bootstrap_approve.py` 终端交互 + `data/finetune/review/` JSONL），不进镜像、远程不可达。评审材料已全在 Postgres：`eval_runs.draft_text`（草稿全文）、`eval_criteria_results`（逐条 verdict+reasoning）、`criteria.guidance`（人工判定标准）。Web 工作台（FastAPI + Jinja2 + Logto 会话 + `require_scope` 权限）已公网部署。动机见 proposal.md。

## Goals / Non-Goals

**Goals**：远程标注员用浏览器完成判官效度验证（盲评）与 gold 标注（核验）；标注身份取自登录会话；支持双人独立标注与一致率计算；导出接现有 `judge_c_gold.jsonl` 飞轮。

**Non-Goals**：MCP 审查工具；标注员自助注册；四元组字段的在线编辑（pilot 阶段导出时组装，需要时再加）；修改判官本身；盲评的技术性防泄密（见风险）。

## Decisions

**D1 任务落库，文件只在导出边界。**
`review_tasks` 表 + join 取材，远程可达且溯源链完整（`review_tasks → eval_criteria_results → eval_runs/rubrics/criteria`）。飞轮仍是文件制，由导出脚本在边界处写 `judge_c_gold.web.jsonl`，不改动 `promote/gate` 流程。
*替代方案*：把 JSONL 批次搬上对象存储、Web 只做壳——省一张表但丢掉引用完整性与条件更新，弃。

**D2 两种批次类型对应两种表单，validity 必须盲评。**
`validity`（论文 M1）：表单只给草稿 + 判定标准，标注员给自己的 pass/fail；模型判定在提交前不出现——否则是"背书"不是独立标注，κ 会被锚定效应抬高。`gold_curation`（飞轮）：表单额外展示模型 verdict+reasoning，approve/reject/skip。
*替代方案*：全部用核验式（`bootstrap_approve.py` 的既有形态）——省一个表单，但论文的一致率不干净，弃。

**D3 双人标注用"槽位行"，不改唯一约束。**
一个 `eval_criteria_result_id` 在同一批次里生成 N 行（N=每条标注人数，默认 2），行之间互不可见对方决策（查询按行隔离）。每行独立条件更新，天然支持 κ 计算。
*替代方案*：一行两列 annotator_a/annotator_b——扩展到 3 人要改表，弃。

**D4 并发用条件更新，不开锁。**
决策提交 `UPDATE review_tasks SET ... WHERE id=:id AND status='pending'`，0 行即冲突，回显已被谁处理。标注规模是几十条量级，行级条件更新足够，不引入 advisory lock。

**D5 权限：新增 `review:annotate` scope，列表只要求登录。**
沿用 `require_scope` 工厂与 `read_only_router`/`write_router` 分层：GET 页面挂 read 路由（登录即可看），决策 POST 挂 write 路由 + `Depends(require_scope("review:annotate"))`。Logto 租户建 `lawbench-annotator` 角色捆绑该 scope（运维步骤，记入 tasks）。现有 `content:write` 不复用——标注员不应能改条款库。

**D6 抽样脚本以 SQL 过滤器为主，V4 运行圈选是操作输入。**
`scripts/finetune/web_review_seed.py` 支持 `--rubric-regex`（如 `^contract_`）、`--types`（合同类别列表）、`--run-ids`（显式钉死）、`--per-type N`（每类抽几条判定）、`--annotators K`、`--batch-id`。V4 那批运行的识别依赖 DB 里的实际分布（按 rubric/时间窗/最优运行），先由操作者用 `--list-runs` 模式查看再钉 `--run-ids`——与论文"逐类结果权威导出"共用同一前置。

**D7 导出与 QC 在一个脚本。**
`scripts/finetune/web_review_export.py`：按 batch 汇总每人决策数、双人条目的吻合率与 Cohen's κ、人-判官一致率（分批次与总计）；`--judge-agreement-warn`（默认 0.98）触发污染告警；approved 的 gold_curation 条目组装四元组（clause_text=草稿、verdict/reasoning=模型判定、legal_base=criterion 关联的法条引用，取不到则空并计数）写出，`review.reviewer=human` + provenance 指回 review task 与源行。κ 手写（2×2 混淆矩阵公式），不引第三方统计库。

**D8 模板与路由复用既有模式。**
`src/web/routes/review.py` 抄 `clauses.py` 的路由形态；模板 `review_list.html`/`review_task.html` 继承 `base.html`，中文文案随模板（项目 UI 即中文，不走 data-labels 的 i18n 表——审查页不在既有标签表内，pilot 不必扩展它）。

## Risks / Trade-offs

- **盲评可被绕过**：标注员若另行打开评估详情页可看到模型判定。Pilot 阶段接受（信任标注员 + 一致率 QC 兜底）；技术性防泄密（不渲染到 DOM）已做，流程性隔离不做。
- **V4 运行圈选未完成前，抽样只能按过滤器近似**——这正是与论文导出共用的前置，任务表设计不受影响（run 维度可追溯，随时重抽一批）。
- **`legal_base` 组装可能为空**：criterion 行不一定带法条引用，导出计数报告，不阻塞。
- **量小**：几十条×2 人，条件更新与无锁设计在当前规模绰绰有余；若未来上千条再议。

## Open Questions

无阻塞项。`--judge-agreement-warn` 阈值默认 0.98，上线后按实际分布调。
