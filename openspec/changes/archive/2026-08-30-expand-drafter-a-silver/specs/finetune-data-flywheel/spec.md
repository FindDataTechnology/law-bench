## MODIFIED Requirements

### Requirement: Drafter-A 配对数据集

系统 SHALL 产出起草训练用配对数据集，每条配对结构为 `(task_desc/slots, 合同正文)`。银牌配对来自两个机器源：`pipeline_runs.filled_text`（LLM 草稿）与 `contract_artifacts` 母版的合成槽位实例化正文（确定性填充）；金牌配对 = 人工核验的合规正文（开源模板经人工抽检 + 后期人工核验）。配对的 `task_desc/slots` 须与正文中的槽位一致。金牌配对的正文 MUST 经过人工核验其合规性。银牌配对（含合成实例化配对）MUST 仅用于 SFT 暖启，不得用于 reward modeling 的正样本。

来自 `pipeline_runs` 的配对 MUST 携带质量元数据：当同一正文存在多条 run 时，保留评分比（`score/max_score`）最高的 run，且被保留配对的 provenance SHALL 记录该 run 的评分比与是否全过（`all_pass`），供训练端按质量降权。来自 `contract_artifacts` 的配对 MUST 携带 `synthetic_slots: true` 合成标记。

SFT 导出（ChatML 化 + 训练/验证切分）时，验证集切分 SHALL 按立场（stance）分层：每个出现于池中的立场按比例进入验证集，单一立场 MUST NOT 全部落入训练侧或验证侧。导出清单（manifest）SHALL 按源（`pipeline_runs` / `contract_artifacts`）分别记录配对计数、立场分布与合成标记计数。

#### Scenario: 银牌配对来自仓内草稿

- **WHEN** 配对数据集从 `pipeline_runs` 抽取一条
- **THEN** 该配对的 `task_desc/slots` 来自 `pipeline_runs.task_desc` 与 `fill_values`
- **AND** 其正文来自 `pipeline_runs.filled_text`
- **AND** 该配对标记 `tier: silver`、`source: warehouse`

#### Scenario: 重复草稿择优保留并带质量元数据

- **WHEN** 多条 `pipeline_runs` 的 `filled_text` 正文逐字节相同但评分不同
- **THEN** 保留评分比最高的那条 run 的配对
- **AND** 该配对 provenance 记录评分比与 `all_pass` 供训练端降权

#### Scenario: 金牌配对须人工核验

- **WHEN** 一条金牌配对被纳入数据集
- **THEN** 该配对的正文已经过人工合规核验
- **AND** 该配对标记 `tier: gold`、`annotated_by: human`

#### Scenario: 槽位与正文一致

- **WHEN** 一条配对的 `task_desc/slots` 声明槽位集合 S
- **THEN** 配对正文中的 `{{slot}}` 占位符（含中文槽位名）已被全部替换为具体值
- **AND** 替换值的键集合 ⊆ S

#### Scenario: 合成配对仅限 SFT 暖启

- **WHEN** 训练数据加载器按 reward 正样本用途过滤物料
- **THEN** `synthetic_slots: true` 的银牌配对被排除在 reward 正样本集合之外
- **AND** 仅人工核验的金牌配对可作为 reward 正样本

#### Scenario: 验证集按立场分层

- **WHEN** SFT 导出对含 balanced/pro_a/pro_b 三种立场的银牌池做训练/验证切分
- **THEN** 每个立场均按切分比例在验证集中出现（该立场样本数 ≥ 切分比例期望时）
- **AND** 单一立场不整体落入训练侧或验证侧
- **AND** 切分在固定种子下可复现

#### Scenario: 清单按源分计

- **WHEN** SFT 导出完成并写导出清单
- **THEN** 清单分别记录来自 `pipeline_runs` 与 `contract_artifacts` 的配对数、各立场分布与合成标记计数
