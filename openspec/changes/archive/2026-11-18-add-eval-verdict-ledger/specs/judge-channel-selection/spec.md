## ADDED Requirements

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
