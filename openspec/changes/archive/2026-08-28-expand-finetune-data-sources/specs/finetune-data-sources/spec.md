## Purpose

把判官-起草飞轮的数据源从已抽取的 6 张表扩到 11 张，补进 `type_validations`/`law_info`/`contract_artifacts`/`core_clauses`/`industry_standard_references`，并新增「候选四元组脚手架构建器」：把仓内合规规则 × 条款正文 × 法条文本交叉配对，产出供人工核验的 silver 脚手架，人工核验后晋金、打开飞轮闸门。所有新物料经既有单点 bronze/silver 守卫，机器产出永不自动晋金。

## ADDED Requirements

### Requirement: 仓库宽表只读抽取

系统 SHALL 把只读、幂等的仓库抽取任务从已覆盖的 6 张表（`clauses`/`pipeline_runs`/`eval_runs`/`eval_criteria_results`/`rubrics`/`criteria`）扩展到 5 张附加表：`type_validations`、`law_info`、`contract_artifacts`、`core_clauses`、`industry_standard_references`。抽取任务对附加表 MUST 保持只读：不得对任何既有表执行写、更新或删除。重复运行同一抽取任务在相同输入下 SHALL 产出逐字节相同的物料清单，且 SHALL NOT 创建重复行。每条附加表物料 MUST 携带 `provenance`（`<table>:<id>`）、`source: warehouse`、`tier`（见分层路由需求）。

#### Scenario: 附加表全量覆盖且只读

- **WHEN** 抽取任务在含 `type_validations`(275)/`law_info`(86)/`contract_artifacts`(362)/`core_clauses`(22)/`industry_standard_references`(22) 行的库上运行
- **THEN** 产出的物料覆盖上述 5 张附加表的全量行
- **AND** 抽取任务的 SQL 全部为 `SELECT`，不包含任何 `INSERT`/`UPDATE`/`DELETE` 针对既有表
- **AND** 第二次运行不写入任何新行到既有表

#### Scenario: 附加表物料带溯源与分层

- **WHEN** 抽取任务产出一条来自 `type_validations` 的物料
- **THEN** 该物料携带 `provenance` 字段，值形如 `type_validations:<id>`（`<id>` 为该行主键，与既有 6 表 `<table>:<id>` 约定一致）
- **AND** 该物料携带 `source: warehouse` 与 `tier` 字段

### Requirement: 新表分层路由

系统 SHALL 为 5 张附加表各指定一个互斥分层标签，并在抽取产出时硬标记：`type_validations` → `gold`（含 `law_ref` 的合规规则，作判官准则脚手架）、`core_clauses` → `gold`（强制条款清单）、`industry_standard_references` → `gold`（成文法指针）、`contract_artifacts` → `raw`（含 `{{slot}}` 的起草骨架，无标签语义）、`law_info` → `bronze`（LLM 生成的法条摘要，仅供检索辅助）。分层标签 MUST 可用于在训练数据加载时按层过滤。

#### Scenario: 附加表各自分层

- **WHEN** 物料池构建完成
- **THEN** 来自 `type_validations` 的物料标记 `tier: gold`
- **AND** 来自 `core_clauses` 的物料标记 `tier: gold`
- **AND** 来自 `industry_standard_references` 的物料标记 `tier: gold`
- **AND** 来自 `contract_artifacts` 的物料标记 `tier: raw`
- **AND** 来自 `law_info` 的物料标记 `tier: bronze`

#### Scenario: law_info 物料被排除在 ground-truth 集合之外

- **WHEN** 训练数据加载器按 ground-truth 用途过滤物料
- **THEN** `tier: bronze` 的 `law_info` 物料被排除在 ground-truth 集合之外
- **AND** 仅 `tier: gold` 的物料进入 ground-truth 集合

### Requirement: 银牌配对去重

系统 SHALL 在导出 Drafter-A 银牌配对时按正文内容去重：当多条 `pipeline_runs.filled_text` 正文逐字节相同时，仅保留一条配对。去重后的银牌暖启池 SHALL 仅含 distinct 正文，且 MUST 记录去重前总数与去重后 distinct 数供审计。去重 MUST NOT 改变被保留配对的 `tier`/`source`/`provenance` 字段。

#### Scenario: 重复正文被合并

- **WHEN** 银牌池含 363 条非空 `filled_text` 但其中仅 151 条 distinct 正文
- **THEN** 导出的银牌配对数据集包含 151 条 distinct 配对
- **AND** 去重审计记录「去重前 363 / 去重后 151」

#### Scenario: 去重不丢字段

- **WHEN** 一条重复正文被合并掉、另一条被保留
- **THEN** 被保留配对的 `tier` 为 `silver`、`source` 为 `warehouse`、`provenance` 形如 `pipeline_runs:<id>`

### Requirement: Judge-C 候选四元组脚手架构建

系统 SHALL 提供一个候选四元组脚手架构建器，按合同类型把 `type_validations` 的合规规则（含 `law_ref` 与 `message`）与 `clauses` 的条款正文、`law_info` 的法条摘要交叉配对，产出候选判官四元组：`legal_base` 取规则的 `law_ref` 与 `law_info` 检索文本、`clause_text` 取条款正文、`verdict` 默认 `fail`（待人工核验）、`reasoning` 取规则的 `message` 与引用。脚手架候选 MUST 标记 `tier: silver`、`provenance: scaffold:machine:<type_validations:id>`、`annotated_by: machine_self_eval`。脚手架候选 SHALL 通过既有四元组 JSON Schema 校验；不通过的候选 MUST 被丢弃并记入缺口。脚手架候选 MUST NOT 自动晋升为 `gold`。

#### Scenario: 脚手架候选按类型配对

- **WHEN** 构建器处理 `contract_type=sale` 的 `type_validations` 规则
- **THEN** 对每条含 `law_ref` 的规则，取同类型的 `clauses` 正文与 `law_info` 法条摘要配对
- **AND** 产出的候选四元组标记 `tier: silver`、`provenance: scaffold:machine:<type_validations:sale:<constraint_id>>`
- **AND** 候选 `verdict` 默认为 `fail`

#### Scenario: 机器脚手架永不晋金

- **WHEN** 构建器产出一条候选四元组
- **THEN** 该候选的 `tier` 为 `silver`，不是 `gold`
- **AND** 该候选的 `annotated_by` 为 `machine_self_eval`，不是 `human_annotated`
- **AND** 既有 bronze/silver 守卫阻止该候选进入 reward 正样本集

### Requirement: 脚手架人工核验晋金

系统 SHALL 仅在人工核验与修正后把脚手架候选晋升为 `gold` 四元组。人工核验产出 MUST 标记 `tier: gold`、`annotated_by: human_annotated`、`reviewer: human`，且 MUST 通过既有四元组 JSON Schema 校验（`verdict=pass` 须含 ≥1 `citation`、机器 pass 被降级为 fail 的规则依然适用）。晋升后的 gold 四元组 SHALL 落 `data/finetune/judge-c/judge_c_gold.jsonl`，使既有飞轮顺序闸门在 Judge-C gold 非空时放行 Drafter-A reward modeling。晋升路径 MUST 是人工产出文件经导出器校验落盘，构建器自身不直接写 gold 文件。

#### Scenario: 人工核验产出晋金

- **WHEN** 人工对一条 `sale` 脚手架候选核验、修正 `reasoning` 并确认 `verdict`
- **THEN** 产出四元组标记 `tier: gold`、`annotated_by: human_annotated`、`reviewer: human`
- **AND** 该四元组通过 `quadruple.schema.json` 校验后落 `judge_c_gold.jsonl`
- **AND** 既有飞轮闸门检测到 gold 非空，放行 Drafter-A reward modeling

#### Scenario: 构建器不直接写 gold

- **WHEN** 脚手架构建器运行完成
- **THEN** 产出的文件仅含 `tier: silver` 候选
- **AND** 不存在构建器直接写入的 `judge_c_gold.jsonl` 记录

### Requirement: law_info 机器生成降级约束

系统 SHALL 把 `law_info` 表（由 doubao/deepseek 两个 LLM 来源生成）的物料硬约束为 `tier: bronze` 检索辅助，MUST NOT 作为权威 `legal_base` 法条原文进入 ground-truth 或 reward 正样本集合。脚手架构建器引用 `law_info` 文本时 MUST 标其为 `legal_base.source: law_info:<llm_source>`，且该引用的存在不使候选晋升为 gold。人工核验若采纳 `law_info` 中的法条表述，MUST 以人工核验后的权威来源重新标注 `legal_base.source`。

#### Scenario: law_info 不作权威法条

- **WHEN** 脚手架构建器把 `law_info(deepseek)` 的法条摘要填入候选的 `legal_base.text`
- **THEN** 该候选 `legal_base.source` 标为 `law_info:deepseek`
- **AND** 该候选 `tier` 仍为 `silver`，不因引用 law_info 晋升为 gold

#### Scenario: 人工核验改标权威来源

- **WHEN** 人工核验一条候选并采纳 `law_info` 中的法条表述
- **THEN** 晋升的 gold 四元组 `legal_base.source` 被改标为人工核验后的权威来源（如 `民法典§509`）
- **AND** 不保留 `law_info:<llm_source>` 作为 gold 的 `legal_base.source`
