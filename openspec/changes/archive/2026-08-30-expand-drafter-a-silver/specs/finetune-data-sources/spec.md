## ADDED Requirements

### Requirement: 合成槽位实例化配对构建

系统 SHALL 提供一个合成槽位实例化构建器，把 `contract_artifacts` 中非 superseded（`superseded_at` 为空）且 `body_text` 非空的母版行转换为 Drafter-A 银牌配对：正文中的 `{{槽位名}}` 占位符（含中文与 ASCII 标识符）MUST 全部被替换为确定性抽取的槽位值，替换后的正文 MUST 不残留任何占位符。占位符名字 MUST 与该行 `slots` 清单一致；出现 `slots` 清单之外的占位符时，该行 MUST 被整行丢弃并计入审计，MUST NOT 部分填充。无法归类到任何值类别的长尾槽位名 SHALL 采用通用法律兜底值填充（如「双方另行协商确定」），MUST NOT 因长尾槽位丢弃整行；使用兜底值的槽位名数与行数 MUST 计入导出审计。槽位值 MUST 由以正文内容为种子的确定性抽取产生：相同输入重复运行 SHALL 产出逐字节相同的配对。产出的配对 MUST 携带：非空 `task_desc`（由合同类型中文名、业务场景、立场确定性合成）、`slots`（名称与填入正文的值一一对应）、`tier: silver`、`provenance: contract_artifacts:<id>`、`annotated_by: machine_generated`、以及 `synthetic_slots: true` 合成标记。合成配对为机器产出，MUST NOT 自动晋升为 gold。

#### Scenario: 模板被完整实例化

- **WHEN** 构建器处理一条非 superseded 的 `contract_artifacts` 行，其正文含 `{{甲方名称}}` 等占位符且全部位于该行 `slots` 清单内
- **THEN** 产出配对的正文不含任何 `{{...}}` 占位符
- **AND** 每个槽位在 `slots` 中记录的值与被替换进正文的值逐字相同
- **AND** 该配对标记 `tier: silver`、`provenance: contract_artifacts:<id>`、`synthetic_slots: true`

#### Scenario: 槽位值如实呈现给训练方

- **WHEN** 一条合成配对被导出为训练样本
- **THEN** user 侧提示词中的槽位值段展示的每个值与该配对 `slots` 记录的值逐字相同
- **AND** assistant 侧正文中出现的对应值与 `slots` 记录的值逐字相同

#### Scenario: superseded 行被跳过

- **WHEN** 一条 `contract_artifacts` 行的 `superseded_at` 非空
- **THEN** 该行不产出任何配对
- **AND** 跳过行为计入导出审计统计

#### Scenario: 清单外占位符整行丢弃

- **WHEN** 一条母版正文含有一个不在该行 `slots` 清单内的占位符
- **THEN** 该行被整行丢弃，不产出部分填充的配对
- **AND** 丢弃计数计入导出审计

#### Scenario: 长尾槽位兜底并计数

- **WHEN** 一条母版正文含有一个无法归类到任何值类别的槽位名
- **THEN** 该槽位以通用法律兜底值填充，该行仍产出配对
- **AND** 使用兜底值的槽位名数与行数计入导出审计

#### Scenario: 确定性重跑逐字节稳定

- **WHEN** 构建器对同一仓库快照连续运行两次
- **THEN** 两次产出的合成配对集合逐字节相同（含槽位值选取）

#### Scenario: 合成配对永不晋金

- **WHEN** 构建器产出一条合成配对
- **THEN** 该配对 `tier` 为 `silver`、`annotated_by` 为 `machine_generated`
- **AND** 既有 bronze/silver 守卫阻止该配对进入 reward 正样本集

## MODIFIED Requirements

### Requirement: 银牌配对去重

系统 SHALL 在导出 Drafter-A 银牌配对时按正文内容做跨源去重：银牌池由 `pipeline_runs.filled_text`（LLM 草稿源）与 `contract_artifacts` 合成槽位实例化正文（母版实例化源）合并而成，当任一源内或多源之间存在逐字节相同的正文时，仅保留一条配对。跨源碰撞时 MUST 优先保留 `pipeline_runs` 源（真实 LLM 草稿）。去重后的银牌暖启池 SHALL 仅含 distinct 正文，且 MUST 按源分别记录去重前总数与去重后 distinct 数供审计。去重 MUST NOT 改变被保留配对的 `tier`/`source`/`provenance` 字段。

#### Scenario: 重复正文被合并

- **WHEN** 银牌池合并后存在多条逐字节相同的正文（无论来自哪个源）
- **THEN** 导出的银牌配对数据集对每条 distinct 正文仅含一条配对
- **AND** 去重审计按源分别记录「去重前 N / 去重后 M」

#### Scenario: 跨源碰撞保留草稿源

- **WHEN** 一条母版实例化正文与一条 `pipeline_runs.filled_text` 正文逐字节相同
- **THEN** 保留 `pipeline_runs` 源的配对，其 `provenance` 形如 `pipeline_runs:<id>`
- **AND** 被丢弃的母版实例化配对计入审计统计

#### Scenario: 去重不丢字段

- **WHEN** 一条重复正文被合并掉、另一条被保留
- **THEN** 被保留配对的 `tier` 为 `silver`、`source` 为 `warehouse`、`provenance` 形如 `pipeline_runs:<id>` 或 `contract_artifacts:<id>`
