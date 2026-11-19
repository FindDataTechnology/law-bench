## Purpose

把「模板带尺子」与「升版要过门」从口头承诺变成可执行的判据：模板声明的每一把尺子必须解析得到，否则模板不可实例化；模板升版必须取到该模板尺子集的结论并过 `no-worse` 门，判不出来时不得放行。没有这条能力，模板的「持续自迭代」永远是凭感觉改。

## ADDED Requirements

### Requirement: 模板声明的尺子必须全部可解析

模板 SHALL 携带 `rubric_refs`（可引用的评测尺子标识清单）。**实例化时**，每条引用 MUST 解析到该域可用的 rubric；任一条解析不到 SHALL 拒绝实例化并以逐条点名的方式报出未解析项。

**保存时** MUST NOT 因未解析而阻断——模板可以分步构造（先词表、后尺子）；保存路径 SHALL 记录未解析项并在模板详情中可见。

`rubric_refs` 为空 SHALL 被视为「无尺子模板」：允许保存、允许建**草稿域**，但该域 SHALL NOT 被视为正式域——草案状态 SHALL 由锚定模板的尺子声明**计算得出**，MUST NOT 新增一列手工维护（手工位会与模板声明分叉，而分叉后没人知道哪一侧为准）。

这是必要的，因为「模板声明我用哪些尺子」若不被校验，该声明只是一句注释，而一个没有尺子的模板永远算不出自己有没有变差。

#### Scenario: 未解析的尺子拒绝实例化
- **WHEN** 模板声明 `rubric_refs: ["contract_sale_v9"]` 而该 rubric 不存在
- **THEN** 实例化被拒绝，错误点名 `contract_sale_v9`

#### Scenario: 保存不因未解析而阻断
- **WHEN** 管理员保存一份声明了尚不存在 rubric 的模板
- **THEN** 保存成功，模板详情列出该未解析项

#### Scenario: 空尺子模板建出的是草稿域
- **WHEN** 一份模板的 `rubric_refs` 为空并被实例化
- **THEN** 域被创建但读面标其为草稿，缺口矩阵对它报「模板不可评」

#### Scenario: 全部解析则可实例化
- **WHEN** 模板声明的三条尺子全部存在于该域的可用集合
- **THEN** 实例化成功，域记录锚定模板版本

### Requirement: 模板升版必须过 no-worse 门

模板从 v_n 升到 v_n+1 时 SHALL 取该模板尺子集的最近一条结论，并按 `no-worse` 门判定：新版本的覆盖度或审计结果 MUST NOT 低于对照基线。

判为 `fail` 的升版 SHALL 被拒绝，旧版本继续在役。判为 `inconclusive`（判不出来：样本不足、尺子不可达、校验器未执行）的升版 SHALL 同样被拒绝，并 MUST 如实报「判不出来」及原因，MUST NOT 以「没有失败证据」为由放行。

**删除尺子本身是退步**：当上一版声明了尺子而新版不再声明时，升版 SHALL 被拒绝——否则「先删尺子再升版」就是绕过本门的现成路径。

首次升版（无可比基线）SHALL 视为「立基线」并允许通过，但读面 MUST NOT 呈现为「变好了」。

#### Scenario: 变差被拒
- **WHEN** v2 的覆盖度低于 v1 且尺子 digest 未变
- **THEN** 升版被拒绝，v1 继续在役，错误报出新旧两版的分数

#### Scenario: 判不出来不得放行
- **WHEN** 升版时尺子不可达、取不到结论
- **THEN** 升版被拒绝，状态如实报 `inconclusive` 及原因

#### Scenario: 删尺子换升版被拒
- **WHEN** v1 声明了三条尺子而 v2 的 `rubric_refs` 为空
- **THEN** 升版被拒绝并说明不接受以移除尺子换取的升版

#### Scenario: 首次升版只立基线
- **WHEN** 某模板第一次升版且无可比历史
- **THEN** 升版通过并标记为立基线，读面不呈现为改进

### Requirement: 尺子口径迁移不得以旧分数对照

当尺子集的 digest 与基线结论所记录的 digest 不一致时，系统 SHALL 标记「口径已迁移」，并把本版按立基线处理：MUST NOT 以旧分数作对照，MUST NOT 发明任何换算系数。

#### Scenario: 换尺子后按立基线处理
- **WHEN** 模板 v2 的尺子集 digest 与 v1 不同
- **THEN** 升版被标记为口径已迁移，不判定为变好或变差，但升版不被阻断

### Requirement: 模板是结论台账的被评对象

模板 SHALL 能作为 `eval-verdict-ledger` 的被评对象出现，`subject_kind` 取 `template`，`subject_key` 为模板名、`subject_version` 为模板版本号。模板结论 SHALL 复用台账既有的四道门闭集与三态结局，MUST NOT 在模板侧另立一套门或结局词汇。

模板结论的尺子地址 SHALL 由该模板 `rubric_refs` 的解析结果派生，MUST NOT 由模板侧自行拼接。

#### Scenario: 模板结论入台账
- **WHEN** 对 `enterprise-base` v1 跑一次覆盖度评估
- **THEN** 台账出现一条 `subject_kind=template`、`subject_key=enterprise-base`、`subject_version=v1` 的记录

#### Scenario: 未知门被拒
- **WHEN** 模板侧提交 `gate="template-better"`
- **THEN** 写入被拒绝并列出四道门闭集

### Requirement: 模板可评性缺口必须独立报出

域的质量视图 SHALL 报告该域锚定模板的「可评性」：`rubric_refs` 的解析率（已解析条数 / 声明条数）。声明为空与解析失败 SHALL 作为独立缺口报出，MUST NOT 计入通过，也 MUST NOT 与「评测柱有数据」合并成一项。

这条与既有的「缺口关闭不等于质量达标」同源：一份模板可以有一个域、有本体单元、有语料，却完全无法被评——它必须自己显示出来。

#### Scenario: 无尺子模板报缺口
- **WHEN** 某域的锚定模板 `rubric_refs` 为空
- **THEN** 质量视图报「模板不可评」缺口，即便该域本体柱与语料柱都非空

#### Scenario: 部分解析按比例报
- **WHEN** 模板声明 4 条尺子、其中 3 条解析成功
- **THEN** 可评性报 3/4，并列出未解析的那一条

### Requirement: 模板改进缺口可派单给舰队

「模板不可评」「模板变差」这类缺口 SHALL 能进入派单路由，目标为舰队（需要判断的活），MUST NOT 默认路由到确定性内核岗位或人工队列。

派单 SHALL 以目标模板为聚合键：同一模板的同一缺口已存在未关闭工单时，再次派单 SHALL 报「已指派」而不是新建重复工单。

#### Scenario: 模板缺口路由到舰队
- **WHEN** 某模板产生「不可评」缺口并被派单
- **THEN** 工单路由到舰队，而不是内核岗位或人工队列

#### Scenario: 重复派单收敛
- **WHEN** 对同一模板的同一缺口再次派单
- **THEN** 报「已指派」并给出既有工单标识，不新建工单
