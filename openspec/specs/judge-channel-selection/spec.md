# judge-channel-selection Specification

## Purpose
判官置信信号不再依赖模型自觉自报：置信从可插拔通道来（首选采样一致率），校准门改为对类不平衡免疫的 human 分层矩阵；通道选型以同一 gold 集上的对照跑为据，全程留痕、不达标如实 fail。

## Requirements

### Requirement: 置信信号通道可插拔

校准通道的置信信号 SHALL 由显式声明的通道产生并逐条留痕（`confidence_source`）；首选通道 = 采样一致率（同一判分独立重复 k 次、多数票占比），k 与温度在记录中可见。任何通道不可用时 SHALL 显式标记该条记录无效/无置信，SHALL NOT 静默回落到模型自报 token 或其他未声明通道。

#### Scenario: 采样一致率产生置信
- **WHEN** 校准跑以 `--samples k>1` 对一对 gold 执行 k 次独立判分
- **THEN** 该条记录带 `confidence_source="vote_share"`、confidence=多数票占比，且 k 次原始判定可追溯

#### Scenario: 通道不可用显式降级
- **WHEN** 声明的通道无法产出置信信号（如原生概率端点不支持）
- **THEN** 记录标记无置信及原因，不落任何伪装成置信的替代值

### Requirement: 分层校准门

校准报告 SHALL 输出按 human 判定分层的混淆矩阵（TP/FP/FN/TN）与派生指标（sensitivity、specificity、balanced accuracy、Cohen's kappa），并按置信通道分桶检验单调性。校准门 SHALL 为 balanced accuracy ≥ 既有阈值 `CALIBRATION_MIN_AGREE`（0.70）且分桶单调；全局 agree 率与旧自报置信分桶 SHALL 降级为诊断字段保留。门不通过时 SHALL 如实 fail，不得以任何后处理改判。

#### Scenario: 类不平衡下的退化解被拦
- **WHEN** 判官对 gold（human 过/不过 ≈ 94/14）全部判不过
- **THEN** specificity 完美但 balanced accuracy ≈0.5，校准门 fail

#### Scenario: 门通过
- **WHEN** 某通道 balanced accuracy ≥0.70 且置信分桶单调
- **THEN** 该轮校准 run 记为通过，矩阵与指标随 run 落库可查

### Requirement: 通道选型对照留痕

同一固定 gold 集上，每个候选通道/模型组合 SHALL 各自完整跑一轮校准并落库（候选标识、调用数、分层矩阵、无效率、成本），结果可按 run 对比。选型结论 SHALL 记录证据（引用 run id）；结论落地为生产判官切换 SHALL 是显式运维动作，选型记录本身 SHALL NOT 自动变更生产判官配置。

#### Scenario: bake-off 对照
- **WHEN** 对 ≥2 候选组合在同一 gold 集上跑校准
- **THEN** 各 run 的候选标识与指标可对比查询，无候选过门时差距如实留痕

#### Scenario: 选型不越权
- **WHEN** 某候选过门且被选中
- **THEN** 生产判官配置保持不变，直到运维显式切换（切换动作另行留痕）

### Requirement: 评分主链隔离

本能力的全部改动 SHALL 限于校准通道与校准报告；生产评分链的评分载荷形状与既有行为 SHALL 保持零变化（新旧报告字段并存、增量兼容）。

#### Scenario: 评分链不受选型影响
- **WHEN** 校准跑使用采样通道或更换候选模型
- **THEN** 生产评分链（合同评分载荷、字段、语义）不变

### Requirement: 校准结论以统一结论形态落库

校准跑 SHALL 以 `eval-verdict-ledger` 规定的结论行落库：被评对象为「判官模型 + 提示词版本」，尺子为该次校准所用 gold 集（携带其 digest），门为 `calibrated`，结局按分层校准门的三态判定（通过 / 未通过 / 判不出）。校准跑的原始产物（混淆矩阵、分桶明细、逐条判定）MAY 留在本能力的既有落点，但结论行 MUST NOT 成为它们的第二副本。

判官的校准状态 SHALL 由这些结论行推导，MUST NOT 另立一份「已校准」标志位；无 `calibrated` 门结论时 SHALL 视为未校准。

#### Scenario: 校准跑产出一条结论行
- **WHEN** 一次校准跑完成
- **THEN** 台账中出现一条门为 `calibrated` 的结论，对象为判官身份、尺子为 gold 集 digest

#### Scenario: 判不出如实记
- **WHEN** 校准样本量低于最小样本门槛或取数失败
- **THEN** 结论为 `inconclusive` 并附原因，不被记为「未通过」

#### Scenario: 状态不另立存储
- **WHEN** 查询某判官是否已校准
- **THEN** 答案由其最近一条校准结论推导，配置与人工声明不参与判定

### Requirement: bake-off 候选对照以结论行留痕

同一固定 gold 集上的候选通道/模型对照跑 SHALL 各自产出一条结论行（对象 = 该候选的判官身份，尺子 = 同一 gold 集 digest），使候选之间可按结论对比查询。对照结果 SHALL NOT 自动变更生产判官配置——切换是显式运维动作。

#### Scenario: 候选各自留痕
- **WHEN** 对两个候选组合在同一 gold 集上跑校准
- **THEN** 各自产生一条同尺子 digest 的结论行，可按对象地址对比

#### Scenario: 选型不越过运维
- **WHEN** 某候选结论过门
- **THEN** 生产判官配置保持不变，直到显式切换并另留记录
