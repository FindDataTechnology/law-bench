## Why

law-bench 现在能用 LLM-as-judge + rubric 自动生成并评分合同（`pipeline_runs` 548 条、`clauses` 6686 条、`eval_runs` 870 条），但这两条产出都是**模型自产自评的飞轮**，不是监督信号：

- **判官不可信**：仓内 `all_pass` 仅 31%、各类型平均通过率 0.137–0.545。`docs/evaluation-system.md` 已自认 judge 存在「结构性误读」（混淆合同正文与评分项、在合同里索要 PASS/FAIL 标记）。用 `eval_criteria_results.verdict/reasoning` 当训练标签 = 蒸馏这个系统性误判。
- **起草缺真值**：`pipeline_runs.filled_text` 是 LLM 填的草稿，量级够暖启（548 条）但不是人工核验过的合规正文。
- **类型覆盖有洞**：约 22 个合同类型有 base 条款但零 pipeline_runs（nda、divorce、mortgage、will…），Drafter 在这些类上无样本。

要做模型微调（判官 + 起草双飞轮），必须先建一套**数据准备子系统**：从仓内 + 开源语料产出带来源/许可证/分层标记的训练集，其中判官 ground-truth 必须人工重写。现在做这件事，是因为飞轮质量上限被这层卡死——判官不纠，起草就没有可信 reward。

## What Changes

- **新增仓库抽取任务**：只读扫描 `clauses`（6686）、`pipeline_runs`（548）、`eval_runs`/`eval_criteria_results`（870），产出原始训练物料；抽取幂等、只读、不改任何既有表。
- **新增开源语料接入（许可证闸门）**：接入 DISC-Law-SFT（Apache-2.0，法律推理 SFT 暖启）、CAIL2018（MIT，裁判推理）、SAMR 模板（起草结构骨架）；**排除** AGPL-3.0（ChatLaw）/ GPL-3.0＋严禁商业（LaWGPT）语料，闸门在接入层强制。
- **新增数据分层 + 溯源**：金（rubric+criteria 人工金牌，直接用）、银（`pipeline_runs.filled_text` LLM 草稿，仅 SFT 暖启）、铜/反例（`eval_criteria_results.verdict` 坏判官产出，**永不作 ground truth**）、原料（`clauses` 结构骨干 + 判官输入池）。每条物料带 `source`（开源仓库 | 仓库表 | 人工标注）+ `license` + `tier`。
- **新增 Judge-C 四元组数据集**：`(法律条文, 合同条款, pass/fail, 推理理由)` 四元组，schema 校验 + 标注规则（推理须含法律依据＋结论；每个 verdict 引用 ≥1 法条/规则；**机器自评一律按 fail 处理，只有人工复核可标 pass**）。
- **新增 Drafter-A 配对数据集**：`(task_desc/slots, 合同正文)` 配对，银牌 = 548 条 `filled_text` 暖启、金牌 = 人工核验合规正文（开源 + 后期人工抽检）。
- **新增飞轮顺序约束**：Judge-C 数据集须先于 Drafter-A reward modeling 存在（判官是起草的 reward 信号）。
- 记录 ~22 个零-pipeline 类型 + custom 条款偏薄（267 条）为已知覆盖缺口，供后续 curation。

非目标：不改既有 `evaluation-rules`/`dual-evaluation`/`contract-drafting-pipeline` 的行为；既有 judge 继续服务于流水线评分，本变更只在其上建**独立的**标注/抽取层。也不在本变更内做模型训练本身（只产数据）。

## Capabilities

### New Capabilities
- `finetune-data-flywheel`: 模型微调数据准备子系统——仓库抽取 + 开源语料接入（许可证闸门）、数据分层与溯源、Judge-C 四元组数据集、Drafter-A 配对数据集、判官→起草飞轮顺序约束。spec 内按抽取/接入/分层/Judge/Drafter/飞轮顺序分需求组。

### Modified Capabilities
<!-- 本变更不改任何既有 spec 的需求。既有 judge/pipeline 行为不变；本变更在其之上新增独立的数据准备层。 -->

## Impact

- **读取**（只读）：`clauses`、`pipeline_runs`、`eval_runs`、`eval_criteria_results`、`rubrics`、`criteria` 表，经现有 `database_url`（pod 内 `psycopg.connect(os.environ['database_url'])`，复用已验证的 kubectl-exec 模式，凭证不外泄）。
- **新增存储**：训练数据集（文件目录或溯源表，记录 `source`/`license`/`tier`/`provenance`）；不改既有表结构。
- **依赖**：开源语料的许可证合规（仅 Apache-2.0/MIT 可入商业微调；AGPL/GPL 排除）；DISC-Law-SFT/CAIL2018 清洗流程。
- **规模基准**（真实仓内数）：Judge 待测池 = 6686 clauses + 548 filled contracts；Drafter 银牌池 = 548；Phase-1 标注种子 = top-5 类型（sale 58 / employment 33 / property_service 27 / technology 23 / film_production 22）×100 ≈ 500 四元组（pilot），全 43 类铺开 ~4K。
- **不受影响**：合同生成/评估/流水线运行时行为、Web/API、MCP 工具对外契约。
