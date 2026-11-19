## MODIFIED Requirements

### Requirement: 双通道评测

评测对象 SHALL 分两通道：文本对象（草稿/答案/报告/条款）走 LLM-judge × rubric × criteria 通道；数据对象（数据集/指标/图谱快照/AI 取数回答）走确定性校验通道（行数/期数/对账/漂移/基线比对，校验器由域包声明）。两通道 SHALL 共用同一套运行记录、compare、趋势与人工复核机器；每条评测记录 SHALL 如实标注其通道。

两通道的每条运行记录 SHALL 同时携带被评对象地址（`subject`：种类 + 键 + 版本）与尺子地址（`ruler`：种类 + 键 + digest），并符合 `eval-verdict-ledger` 规定的门与结局词汇；通道 MUST NOT 决定记录形状——两条通道落进同一张表、同一组字段，只在通道字段上不同。

#### Scenario: 数据对象确定性评测
- **WHEN** 对一个数据对象（如某指标数据集的快照）发起评测，其域包声明了确定性校验器
- **THEN** 评测运行逐条执行校验器并落 per-check verdict（数值级对/错），不调用 LLM judge，限流与模型故障不影响其结果

#### Scenario: 数据 QA 金集评测 AI 用数
- **WHEN** 以数据 QA 金集（题目绑定真实数据集与期望结果）对 AI 取数/答数对象发起评测
- **THEN** 每题按期望结果判定正误并落可追溯记录（题目→数据集→期望→实际→verdict），可进入 compare 与趋势

#### Scenario: 通道如实标注
- **WHEN** 查询任一评测运行的记录
- **THEN** 记录含通道字段（text/data），下游聚合与展示按通道区分，不混淆

#### Scenario: 两通道记录同形
- **WHEN** 比较一条文本通道与一条数据通道的运行记录
- **THEN** 两者的对象地址、尺子地址、门与结局字段同形，可在同一张趋势图上按对象聚合

### Requirement: meta-eval（尺子的尺子）

平台 SHALL 对判官与评测套件本身做度量：judge 对 gold 的校准（按置信分档的准确率与单调性）与评测套件的漂移检测 SHALL 为一等运行记录，与被评对象共用趋势机器；判官校准结果 SHALL 随 judge 模型与提示词版本留痕。现行判官（all_pass 仅 31%、存在结构性误读）SHALL 作为第一个校准对象，其结构性误读修复前 SHALL NOT 被任何域包声明为可信 gold 信号源。

校准运行 SHALL 以 `eval-verdict-ledger` 的结论形态落库：被评对象为「该判官的模型 + 提示词版本」，尺子为该次校准所用 gold 集（携带其 digest），门为 `calibrated`。判官的校准状态 SHALL 由这些结论行推导，MUST NOT 另立一份「是否已校准」的独立存储。

#### Scenario: judge 校准运行
- **WHEN** 对某 judge（模型+提示词版本）在指定 gold 集上发起校准运行
- **THEN** 产出按置信分档的准确率矩阵与单调性结论，落库可查，纳入该 judge 的版本档案

#### Scenario: 未校准判官受限
- **WHEN** 某域包尝试将未通过校准（或校准失败）的 judge 声明为 gold 信号源
- **THEN** 声明被拒绝并如实指明「judge 未通过校准」，不产生该域的 gold 标注

#### Scenario: 校准结论携带 gold 集 digest
- **WHEN** 一次校准运行落库
- **THEN** 其尺子地址携带该 gold 集的 digest，换 gold 集后新旧校准结论不可直接相比

#### Scenario: 校准状态由结论推导
- **WHEN** 某判官被问到「是否已校准」
- **THEN** 答案取自其最近一条 `calibrated` 门结论的结局，MUST NOT 来自配置项或人工声明
