## Purpose

为判官（Judge C）与起草（Drafter A）双飞轮微调产出**可溯源、分层、许可证合规**的训练数据：只读抽取仓内 `clauses`/`pipeline_runs`/`eval_runs` 物料，按许可证闸门接入开源语料，把物料分成金/银/铜/原料四层并打上来源与许可证标记，人工产出 Judge-C 四元组数据集与 Drafter-A 配对数据集，并强制「判官先于起草 reward modeling」的飞轮顺序。

## ADDED Requirements

### Requirement: 仓库只读抽取任务

系统 SHALL 提供一个幂等、只读的抽取任务，扫描仓内 `clauses`、`pipeline_runs`、`eval_runs`、`eval_criteria_results`、`rubrics`、`criteria` 表，产出原始训练物料（条款正文、已填合同正文、逐条判定与理由、rubric 规则）。抽取任务 MUST 只读，不得对任何既有表执行写、更新或删除。抽取产出 MUST 带溯源字段 `provenance`（仓内表名 + 行 id）、`source: warehouse`、`tier`（见分层需求）。重复运行同一抽取任务 SHALL 产出逐字节相同的物料清单（相同输入下），且 SHALL NOT 创建重复行。

#### Scenario: 幂等只读抽取

- **WHEN** 抽取任务对当前数据库运行两次
- **THEN** 两次产出的物料清单条数完全相同
- **AND** 第二次运行不写入任何新行到 `clauses`/`pipeline_runs`/`eval_runs`/`eval_criteria_results`/`rubrics`/`criteria`
- **AND** 抽取任务的 SQL 全部为 `SELECT`，不包含任何 `INSERT`/`UPDATE`/`DELETE` 针对既有表

#### Scenario: 每条物料带溯源

- **WHEN** 抽取任务产出一条来自 `pipeline_runs` 的物料
- **THEN** 该物料携带 `provenance` 字段，值形如 `pipeline_runs:<id>`
- **AND** 该物料携带 `source: warehouse` 与 `tier` 字段

#### Scenario: 覆盖全量仓内物料

- **WHEN** 抽取任务在含 6686 clauses / 548 pipeline_runs / 870 eval_runs 的库上运行
- **THEN** 产出的条款物料覆盖 `clauses` 表的全量行
- **AND** 产出的已填合同物料覆盖 `pipeline_runs.filled_text` 的全量非空行
- **AND** 产出的逐条判定物料覆盖 `eval_criteria_results` 的全量行

### Requirement: 开源语料许可证闸门

系统 SHALL 在开源语料接入层强制一个许可证闸门：仅允许标注为 Apache-2.0 或 MIT 许可证的开源语料进入商业可微调的训练物料池。标注为 AGPL-3.0、GPL-3.0、或「严禁商业」的语料 MUST 被拒绝，不得进入训练物料池。每个开源语料包 MUST 在接入时携带 `source`（开源仓库名）、`license`（SPDX 标识）、`tier` 字段，并记录原始下载来源。

#### Scenario: Apache-2.0 语料获准入池

- **WHEN** 接入层收到一个标注 `license: Apache-2.0` 的语料包（如 DISC-Law-SFT）
- **THEN** 该语料包进入训练物料池
- **AND** 其物料标记 `source: <repo>`、`license: Apache-2.0`、`tier: silver`（暖启）或 `tier: gold`（经人工核验后）

#### Scenario: AGPL/GPL 语料被拒绝

- **WHEN** 接入层收到一个标注 `license: AGPL-3.0`（如 ChatLaw）或 `license: GPL-3.0` + 严禁商业（如 LaWGPT）的语料包
- **THEN** 该语料包被拒绝，不进入训练物料池
- **AND** 拒绝事件被记录（语料名 + 许可证 + 拒绝原因）
- **AND** 训练物料池中不存在来自该语料包的任何物料

#### Scenario: 缺许可证的语料默认拒绝

- **WHEN** 接入层收到一个未标注许可证或许可证字段为空的语料包
- **THEN** 该语料包被拒绝，不进入训练物料池
- **AND** 拒绝原因记录为「缺少许可证声明」

### Requirement: 数据分层与溯源标记

系统 SHALL 把全部训练物料（仓内抽取 + 开源接入 + 人工标注）分成四个互斥层级，并为每条物料打上分层标签：**gold**（人工金牌，rubric+criteria 与人工核验正文，可直接用作 ground truth）、**silver**（LLM 产出的草稿，`pipeline_runs.filled_text`，仅限 SFT 暖启）、**bronze**（坏判官产出，`eval_criteria_results.verdict`，**永不作 ground truth，仅供失败分析**）、**raw**（结构骨干，`clauses` 与判官输入池）。每条物料 MUST 携带 `source`、`license`、`tier` 三字段。分层标签 MUST 可用于在训练数据加载时按层过滤。

#### Scenario: 四层互斥且各自标记

- **WHEN** 物料池构建完成
- **THEN** 任一物料恰好属于 gold / silver / bronze / raw 之一
- **AND** 来自 `eval_criteria_results.verdict` 的物料标记 `tier: bronze`
- **AND** 来自 `pipeline_runs.filled_text` 的物料标记 `tier: silver`
- **AND** 来自人工核验的物料标记 `tier: gold`
- **AND** 来自 `clauses` 表的物料标记 `tier: raw`

#### Scenario: bronze 永不作 ground truth

- **WHEN** 训练数据加载器按 ground-truth 用途过滤物料
- **THEN** `tier: bronze` 的物料被排除在 ground-truth 集合之外
- **AND** 仅 `tier: gold` 的物料进入 ground-truth 集合

#### Scenario: 按层过滤加载

- **WHEN** 训练数据加载器收到指令「仅加载 silver 及以上」
- **THEN** 加载器返回 `tier` 为 gold 或 silver 的物料
- **AND** 不返回 bronze 或 raw 物料

### Requirement: Judge-C 四元组数据集

系统 SHALL 产出判官训练用四元组数据集，每条四元组结构为 `(法律条文/合同条款, 评审规则, pass/fail 判定, 推理理由)`。四元组 MUST 通过 schema 校验：法律条文须含来源与正文、合同条款须含正文与分节、判定须为 `pass` 或 `fail` 之一、推理理由须同时包含法律依据与结论。每个四元组的 verdict MUST 引用至少一条法律条文或评审规则。**机器自评产出（来自 `eval_criteria_results`）一律按 `fail` 处理或丢弃，只有人工复核可把四元组标为 `pass`。** 四元组数据集 MUST 记录标注者来源（人工 vs 机器）。

#### Scenario: 四元组 schema 校验

- **WHEN** 一条候选四元组的推理理由缺少法律依据
- **THEN** 该四元组被 schema 校验拒绝
- **AND** 被拒绝的四元组不进入 Judge-C 数据集
- **AND** 拒绝原因记录为「推理理由缺少法律依据」

#### Scenario: 机器自评不产生 pass

- **WHEN** 一条来自 `eval_criteria_results` 的判定其机器 verdict 为 `pass`
- **THEN** 该判定在进入四元组数据集时被降级为 `fail` 或丢弃
- **AND** 该四元组若保留则标注来源为 `machine_self_eval`，不标注 `pass`

#### Scenario: 人工标 pass 须含法律依据

- **WHEN** 人工标注一条 `pass` 判定的四元组
- **THEN** 该四元组的推理理由引用至少一条法律条文或评审规则
- **AND** 该四元组标注来源为 `human_annotated`
- **AND** 该四元组 `tier` 标记为 `gold`

### Requirement: Drafter-A 配对数据集

系统 SHALL 产出起草训练用配对数据集，每条配对结构为 `(task_desc/slots, 合同正文)`。银牌配对 = `pipeline_runs.filled_text`（548 条暖启），金牌配对 = 人工核验的合规正文（开源模板经人工抽检 + 后期人工核验）。配对的 `task_desc/slots` 须与正文中的槽位一致。金牌配对的正文 MUST 经过人工核验其合规性。银牌配对 MUST 仅用于 SFT 暖启，不得用于 reward modeling 的正样本。

#### Scenario: 银牌配对来自仓内草稿

- **WHEN** 配对数据集从 `pipeline_runs` 抽取一条
- **THEN** 该配对的 `task_desc/slots` 来自 `pipeline_runs.task_desc` 与 `fill_values`
- **AND** 其正文来自 `pipeline_runs.filled_text`
- **AND** 该配对标记 `tier: silver`、`source: warehouse`

#### Scenario: 金牌配对须人工核验

- **WHEN** 一条金牌配对被纳入数据集
- **THEN** 该配对的正文已经过人工合规核验
- **AND** 该配对标记 `tier: gold`、`annotated_by: human`

#### Scenario: 槽位与正文一致

- **WHEN** 一条配对的 `task_desc/slots` 声明槽位集合 S
- **THEN** 配对正文中的 `{{slot}}` 占位符已被全部替换为具体值
- **AND** 替换值的键集合 ⊆ S

### Requirement: 飞轮顺序约束

系统 SHALL 强制判官数据集先于起草 reward modeling 存在的飞轮顺序：Judge-C 四元组数据集（至少 gold 子集）必须在其被用作 Drafter-A reward 信号之前完成构建并通过校验。当 Judge-C 数据集为空或未通过 schema 校验时，Drafter-A 的 reward modeling 阶段 SHALL 被阻断并报错，而非静默使用银牌草稿当正样本。

#### Scenario: 判官先于起草 reward modeling

- **WHEN** 启动 Drafter-A reward modeling 阶段
- **THEN** 系统检查 Judge-C gold 四元组数据集是否存在且非空
- **AND** 若不存在或为空，reward modeling 阶段被阻断并报错「Judge-C 数据集未就绪」
- **AND** 不使用 `tier: silver` 草稿作为 reward 正样本

#### Scenario: 判官就绪后释放起草

- **WHEN** Judge-C gold 四元组数据集已构建且通过 schema 校验
- **THEN** Drafter-A reward modeling 阶段被允许启动
- **AND** Judge-C 模型作为 reward 信号驱动起草迭代

### Requirement: 覆盖缺口记录

系统 SHALL 把已知的训练数据覆盖缺口记录为显式的缺口清单，供后续 curation：约 22 个有 base 条款但零 `pipeline_runs` 的合同类型（如 nda、divorce、mortgage、will 等），以及 custom 立场条款偏薄（267 条）。缺口清单 MUST 可被抽取任务幂等刷新，且 MUST 不阻塞其他需求。

#### Scenario: 零-pipeline 类型被记录

- **WHEN** 抽取任务扫描到某合同类型在 `clauses` 表有 base 条款但在 `pipeline_runs` 表零行
- **THEN** 该类型被加入覆盖缺口清单，缺口类别为 `zero_pipeline_runs`
- **AND** 重新运行抽取任务刷新该清单，不产生重复缺口条目

#### Scenario: custom 薄弱被记录

- **WHEN** 抽取任务统计 `clauses` 表 `tags.source = custom` 的行数
- **THEN** 若总数低于阈值（如 < 500），记一条缺口 `custom_thin`，附当前实际行数
- **AND** 该缺口不阻断 Judge-C 或 Drafter-A 数据集构建
