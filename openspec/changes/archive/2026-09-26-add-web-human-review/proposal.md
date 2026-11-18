# add-web-human-review — Web 端人工审查

## Why

人工审查（判官效度验证 + Judge-C gold 标注）目前只有本地流程：`scripts/finetune/bootstrap_approve.py` 的终端交互，以及 `data/finetune/review/` 下的 JSONL 手工编辑。该目录不进 Docker 镜像，远程标注员无法触达；且 `review/done/` 至今为空——人工审查从未实际执行过。评审所需的全部材料（草稿全文、逐条判定与理由、人工判定标准）已经都在 Postgres（`eval_runs.draft_text` / `eval_criteria_results` / `criteria`），Web 工作台已公网部署并带 Logto 登录。把人工审查搬上 Web 是让远程的人参与的最短路径，同时解决两个悬案：论文的判官效度验证（M1）与微调飞轮的人工 gold 产出。

## What Changes

- 新增 `review_tasks` 表：以 `eval_criteria_results` 行为审查对象（`run_id` + `criterion_id` 引用，保留完整溯源链），携带 `batch_type`（`validity` 效度验证 / `gold_curation` gold 标注）、分配信息、状态（pending/approved/rejected/skipped）、标注员（取自登录身份，不手填）、备注与时间戳。
- 新增 Web 审查入口 `/review`：队列列表页 + 决策表单页，复用 `/clauses/review` 已有的列表/审核交互模式；表单同屏展示草稿文本、评审项的人工判定标准、模型判定与模型理由——标注员看到判官看到的一切，再作独立判断。
- 新增 Logto 角色 `lawbench-annotator`（权限沿用现有 RBAC 机制）：远程标注员由管理员发放账号即可参与，无对外注册。
- 新增抽样脚本：从可识别的 V4 那批 43 类运行中分层抽样生成 `validity` 任务，支持每条多标注员独立标注（默认 2 人），供计算标注员间一致率（κ）与人工-判官一致率。
- 新增导出脚本：`approved` 任务导出为 `judge_c_gold.jsonl`（`reviewer=human` 溯源，接现有 promote/gate 流程），并内置质量检查——包括"某标注员与判官一致率反常偏高"的污染告警（机器代打的典型信号）。
- 非目标：MCP 审查工具（本轮明确不做，决策入口只走 Web）；标注员自助注册；修改判官本身。

## Capabilities

### New Capabilities

- `human-review-web`: Web 端人工审查能力——审查任务的生成与抽样、分配与锁、决策表单、权限边界、标注溯源与导出质量检查的行为契约。

### Modified Capabilities

（无——权限校验沿用现有 web 认证/RBAC 机制，不改变其既有需求。）

## Impact

- **代码**：`src/web/routes/`（新增 review 路由模块）、`src/web/templates/`（新增列表与表单页）、`src/eval/store.py`（`review_tasks` 表进 schema 源，随 `ensure_schema` 自愈建表）、`scripts/finetune/`（抽样与导出两个脚本）。
- **依赖**：无新增第三方依赖（FastAPI/Jinja2/psycopg 均已在用）。
- **外部系统**：Logto 租户需新增 `lawbench-annotator` 角色与对应权限 scope；k3s 部署形态不变（同一工作负载）。
- **数据**：`review_tasks` 为新表，不动既有表；`judge_c_gold.jsonl` 等导出产物落在开发机 `data/finetune/judge-c/`（保持现状：飞轮数据不进镜像）。
- **前置依赖**：需要先能在库中圈定 V4 那批 43 类的运行（`eval_runs`/`pipeline_runs` 的筛选条件），这与论文"逐类结果权威导出"是同一个前置，应一并完成。
