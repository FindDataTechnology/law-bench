## MODIFIED Requirements

### Requirement: Judge-C 四元组数据集

系统 SHALL 产出判官训练用四元组数据集，每条四元组结构为 `(法律条文/合同条款, 评审规则, pass/fail 判定, 推理理由)`。四元组 MUST 通过 schema 校验：法律条文须含来源与正文、合同条款须含正文与分节、判定须为 `pass` 或 `fail` 之一、推理理由须同时包含法律依据与结论。每个四元组的 verdict MUST 引用至少一条法律条文或评审规则。四元组数据集 MUST 记录标注者来源（`human`、`ai_reviewer`、`machine_self_eval` 三者之一）。

标注者层级与判定权限：

- `machine_self_eval`（来自 `eval_criteria_results` 的机器自评）一律按 `fail` 处理或丢弃，永不产生 `pass`，`tier` 标记为 `bronze`，永不作 ground truth。
- `ai_reviewer`（对真实 `(已填合同, 规则)` 配对由 LLM 重新判定）MAY 产出 `pass` 或 `fail`，`tier` 标记为 `gold`，可作为 ground truth。
- `human`（人工复核）MAY 产出 `pass` 或 `fail`，`tier` 标记为 `gold`，可作为 ground truth。

规范化金牌文件（canonical gold file）MUST 仅由已验证零泄漏的源数据集合并而成。泄漏定义：某四元组的 `clause_text.body` 等于或派生自其自身的 `reasoning.justification`（判官自己的推理被复制进输入正文，构成反向监督）。合并后的金牌超集 MUST 满足 0% 泄漏（不存在任何 `clause_text.body` 等于 `reasoning.justification` 的四元组）。

判官就绪闸门（flywheel gate）MUST 基于零泄漏的金牌超集判定是否释放 Drafter-A reward modeling：当金牌超集为空或未通过零泄漏校验时，reward modeling 阶段 SHALL 被阻断并报错；闸门 SHALL NOT 基于可能携带预重定基准泄漏的陈旧物化文件通过。

覆盖缺口闭合：对于尚无金牌四元组的合同类型（即已抽取到 base 条款与规则、但未生成 `ai_reviewer` 判定的配对），系统 SHALL 通过对真实 `(已填合同, 规则)` 配对重新运行 `ai_reviewer` 判定来闭合缺口。生成 MUST 可断点续跑：重新运行 SHALL 按 provenance id 跳过已完成的配对，仅判定未完成配对，既不重复判定也不遗漏已完成行，使中断的运行可在上游恢复后继续而不破坏已有金牌。

#### Scenario: 四元组 schema 校验

- **WHEN** 一条候选四元组的推理理由缺少法律依据
- **THEN** 该四元组被 schema 校验拒绝
- **AND** 被拒绝的四元组不进入 Judge-C 数据集
- **AND** 拒绝原因记录为「推理理由缺少法律依据」

#### Scenario: 机器自评不产生 pass

- **WHEN** 一条来自 `eval_criteria_results` 的判定其机器 verdict 为 `pass`
- **THEN** 该判定在进入四元组数据集时被降级为 `fail` 或丢弃
- **AND** 该四元组若保留则标注来源为 `machine_self_eval`、`tier: bronze`，不标注 `pass`
- **AND** 该四元组永不作 ground truth

#### Scenario: ai_reviewer 可产出 pass

- **WHEN** 一个 `ai_reviewer` 对真实 `(已填合同, 规则)` 配对判定为 `pass` 且推理理由含法律依据
- **THEN** 该四元组进入 Judge-C 金牌数据集，`verdict: pass`
- **AND** 该四元组标注来源为 `ai_reviewer`、`tier: gold`
- **AND** 该四元组可作为 ground truth

#### Scenario: 人工标 pass 须含法律依据

- **WHEN** 人工标注一条 `pass` 判定的四元组
- **THEN** 该四元组的推理理由引用至少一条法律条文或评审规则
- **AND** 该四元组标注来源为 `human`、`tier: gold`
- **AND** 该四元组可作为 ground truth

#### Scenario: 规范化金牌仅由零泄漏源合并

- **WHEN** 系统从多个源数据集合并规范化金牌文件
- **THEN** 每个参与合并的源数据集已独立验证为 0% 泄漏
- **AND** 合并后的金牌超集经验证为 0% 泄漏（无任何四元组的 `clause_text.body` 等于其 `reasoning.justification`）
- **AND** 存在泄漏的行被丢弃而非降权（泄漏行是反向监督，不可保留）

#### Scenario: 闸门基于零泄漏金牌超集

- **WHEN** 判官就绪闸门判定是否释放 Drafter-A reward modeling
- **THEN** 闸门读取零泄漏的金牌超集
- **AND** 当金牌超集为空或未通过零泄漏校验时，reward modeling 被阻断并报错「Judge-C 数据集未就绪」
- **AND** 闸门 SHALL NOT 基于携带预重定基准泄漏的陈旧物化文件通过

#### Scenario: ai_reviewer 生成可断点续跑

- **WHEN** 一个 `ai_reviewer` 生成运行在上游故障后重新启动
- **THEN** 重新运行按 provenance id 跳过已写入的配对
- **AND** 仅判定未完成的配对
- **AND** 既不重复判定已完成配对，也不遗漏任何已完成行
- **AND** 已有金牌文件不被破坏，新判定的四元组被追加
