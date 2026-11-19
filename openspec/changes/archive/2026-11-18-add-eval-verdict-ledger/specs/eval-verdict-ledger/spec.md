## Purpose

把「这次评测能不能和上次比」从一句口头承诺变成一条可查询的记录：每条评测结论必须指名被评对象与尺子的稳定身份、它跟谁比、按哪道门判、以及判出的是通过、失败还是**无结论**。它是跨线迭代可度量的底座——没有它，自动修正与自动迭代永远无法证明自己变好了。

## ADDED Requirements

### Requirement: 评测结论必须指名对象与尺子

每条评测结论 SHALL 是一条可查询记录，至少包含：**被评对象地址**（`subject`：种类 + 键 + 版本）、**尺子地址**（`ruler`：种类 + 键 + digest）、通道、门、结局、逐条证据、判官身份（若走判官通道）、产生时间与产生者。

被评对象地址的版本 SHALL 能区分同一对象的不同代（同一份 pack 的 v3 与 v4 不是同一对象）；对象无内生版本时 SHALL 以其内容指纹或不可变快照标识充任，MUST NOT 留空或以「最新」代替。尺子地址 SHALL 携带与发布面同一份实现算出的 digest，MUST NOT 由本能力另写一份 digest 逻辑。

一条结论缺少对象地址或尺子地址时 SHALL 被拒绝写入，错误 SHALL 指明缺哪一项；MUST NOT 以空值落库后再由读面猜测。

#### Scenario: 缺对象地址拒绝写入
- **WHEN** 评测调用方未提供被评对象地址或版本为空
- **THEN** 写入被拒并指明缺项，台账不产生该行

#### Scenario: 同一对象的两代可区分
- **WHEN** 同一 pack 的 v3 与 v4 各有一条结论
- **THEN** 两条记录的对象地址不同，按对象聚合趋势时不会被合成一条线

#### Scenario: 尺子 digest 与发布面一致
- **WHEN** 某 rubric 已经由发布面发布并持有 digest
- **THEN** 以该 rubric 评出的结论所记 digest 与发布面返回的 digest 逐字节相等

### Requirement: 四道门是闭集，门不可自创

每条结论的门 SHALL 是以下之一：`no-worse`（候选不劣于对照）、`regression`（相对基线降幅超阈值即拦）、`all-pass`（逐条全过）、`calibrated`（尺子或判官自身可信）。写入未知门值 SHALL 被拒绝并列出闭集成员，MUST NOT 静默收下或映射到一个「差不多」的门。

门 SHALL 只是结论的分类标签：本能力 MUST NOT 重新实现任何一条既有产品线的判定逻辑，各线保有自己的门槛与阈值。

#### Scenario: 未知门被拒
- **WHEN** 调用方以 `gate="better-than"` 提交结论
- **THEN** 写入被拒并列出四道门的取值

#### Scenario: 同一判定逻辑不出现第二份
- **WHEN** 检视某线既有门的实现
- **THEN** 该线仍以原有实现判定通过与否，本台账只接收其结果与分类标签

### Requirement: 结局是三态且「无结论」不得冒充

结局 SHALL 是 `pass`、`fail`、`inconclusive` 之一。样本量不足、判官车道不可达、校验器未执行、超时等**判不出来**的情形 SHALL 记 `inconclusive` 并附原因，MUST NOT 折成 `fail` 或 `pass`。

`inconclusive` SHALL NOT 被任何晋升闸当通过处理，SHALL NOT 被计入通过率分母以外的统计；读面呈现时 SHALL 与 `fail` 分列。

#### Scenario: 车道不可达记无结论
- **WHEN** 一次评测因判官端点不可达而未能产出任何判据
- **THEN** 结论为 `inconclusive` 且原因如实记录，不落为 `fail`

#### Scenario: 无结论不得晋升
- **WHEN** 某候选的最新结论为 `inconclusive`
- **THEN** 晋升闸拒绝以该结论放行，提示需重跑评测

#### Scenario: 三态分列呈现
- **WHEN** 一个对象同时有 `fail` 与 `inconclusive` 的历史结论
- **THEN** 读面分别计数，不合并成「未通过」

### Requirement: 结论必须指名基线或声明无可比历史

一条结论 SHALL 携带其对照基线（指向既有结论的引用），或显式声明「无可比历史」。**首次评测 SHALL 只构成立基线，MUST NOT 构成本次改动的进步证据。**

当基线的尺子 digest 与本条不一致时，系统 SHALL 标记「口径已迁移」并把本条视为立基线，MUST NOT 以旧分数作对照，也 MUST NOT 发明任何换算系数。

#### Scenario: 首次评测不构成进步
- **WHEN** 某对象第一次被评测且全部判据通过
- **THEN** 结论记为立基线（无可比历史），读面不呈现为「变好了」

#### Scenario: 换尺子后不可比
- **WHEN** 一条结论要引用的基线所用的 ruler digest 与本条不同
- **THEN** 本条标「口径已迁移」并按立基线处理，不以基线分数计算差值

#### Scenario: 同尺子可算差
- **WHEN** 基线与本条的 ruler digest 相同
- **THEN** 读面可呈现两次结论间的可核对差值与其逐条差异

### Requirement: 未校准判官的结论标 provisional 且不足以单独晋升

走判官通道的结论 SHALL 记录判官身份（模型 + 提示词版本），并据该判官当前的校准状态标 `provisional` 与否。判官未通过分层校准门时，其结论 SHALL 标 `provisional`，且 SHALL NOT 单独构成晋升或发版的依据。

校准状态 SHALL 取自现有校准记录，MUST NOT 由调用方自称；无校准记录时 SHALL 视为未校准。

#### Scenario: 未校准判官结论被标记
- **WHEN** 某判官无通过的校准记录而产出一条结论
- **THEN** 该结论带 `provisional` 标记，读面明示「判官未过校准门」

#### Scenario: provisional 不足以晋升
- **WHEN** 某候选只有 `provisional` 的通过结论
- **THEN** 晋升闸拒绝以它为依据，提示需校准判官或补人工核验

### Requirement: 晋升与发版后强制复测

任一晋升或发版动作 SHALL 产生一条待复测项，指名被改动的对象地址与其改动前的基线结论；复测结论 SHALL 引用该基线。

晋升动作本身 MUST NOT 因缺少复测而被拒绝，也 MUST NOT 自动触发复测执行——本要求只保证复测项被登记、可被读到、且不被静默丢弃。

#### Scenario: 晋升后出现待复测项
- **WHEN** 某候选被晋升为新版本
- **THEN** 台账中出现一条待复测项，指向新版本地址与晋升前的基线结论

#### Scenario: 复测引用晋升前基线
- **WHEN** 对某已晋升版本执行复测
- **THEN** 复测结论的基线指向晋升前的结论，口径不一致时按口径迁移规则处理

### Requirement: 逐条证据与原件引用代替汇总分

每条结论 SHALL 携带逐条判据结果（判据标识 + 判定 + 理由）或逐项校验结果，并 MAY 附原件引用（报告路径、工单标识、产物 digest）。汇总分 SHALL 只是诊断字段，MUST NOT 作为复核的唯一依据。

本地原件（评测报告 JSON、工单、覆盖报告）SHALL 保留在原线，本台账 MUST NOT 成为它们的第二副本；台账只存结论行与指向原件的引用。

#### Scenario: 复核者读逐条判据
- **WHEN** 复核者检视一条结论
- **THEN** 可逐条读到判据标识与判定，不必只依赖汇总分

#### Scenario: 原件不搬家
- **WHEN** 某线的评测报告已存在本地
- **THEN** 台账记录指向它的引用，报告本体仍在原线

### Requirement: 运行台账与评测结论互链

一次运行产出评测结论时，运行记录 SHALL 可指向其产出的结论；结论 SHALL 可回溯到产出它的运行。互链 MUST NOT 复制对方的字段内容——两处各存一份必然漂移。

#### Scenario: 运行回写可追到结论
- **WHEN** 一支舰队回合完成后回写运行台账并产出评测结论
- **THEN** 运行行可指向该结论，结论可回溯到该运行

#### Scenario: 未产出结论的运行不伪造链接
- **WHEN** 一次运行没有产出任何评测结论
- **THEN** 运行行的结论引用为空，不指向任意一个「最近的」结论

### Requirement: 结论台账的机器读面

结论台账 SHALL 提供机器通道的只读端点，使不在本进程内的消费者（另一产品线的舰队、运维脚本）能读到结论：

- `GET /api/v1/distribution/{domain_key}/verdicts` —— 该域（含祖先链）的结论列表，可按 `subject_kind` / `subject_key` / `gate` / `outcome` 筛选与限量；
- `GET /api/v1/distribution/{domain_key}/verdicts/{run_id}` —— 单条结论与其逐条判据；
- `GET /api/v1/distribution/{domain_key}/rulers` —— 该域可用尺子及其规范 digest。

鉴权 SHALL 沿用发布面既有的机器凭据与三态判定（未带凭据 401、未登记/已吊销 403、越域 403），且 SHALL 仅允许 `fleet` 种类的登记读取。域归属 SHALL 与运行列表用同一口径（`rubric_domain_id` + 祖先链），使两者对「哪些属于本域」不可能给出不同答案。

`gate` 与 `outcome` SHALL 是按闭集校验的筛选参数：未知值 SHALL 以 400 拒绝并列出闭集，MUST NOT 返回 200 空列表——后者与「确实没有这类结论」是两句不同的话。

单条结论的域归属不成立时 SHALL 返回 404 而非 403：403 会确认该 id 在别处存在。

本面 SHALL 只读：任何端点 MUST NOT 创建结论、MUST NOT 触发评测。

#### Scenario: 消费者读本域结论
- **WHEN** 绑定域 A 的舰队以其机器凭据请求 A 的结论列表
- **THEN** 只返回归属 A 的结论，`inconclusive` 与其他结局一并返回且不被改写

#### Scenario: 越域读取被拒
- **WHEN** 绑定域 A 的凭据请求域 B 的结论列表
- **THEN** 403 报明该域不在绑定范围，B 的任何结论零出现

#### Scenario: 未知门拒绝而非空列表
- **WHEN** 调用方以 `gate=better-than` 请求结论列表
- **THEN** 400 拒绝并列出四道门的合法取值

#### Scenario: 他域结论 id 不泄露存在性
- **WHEN** 调用方以其域凭据请求另一个域的结论 id
- **THEN** 返回 404 而非 403

#### Scenario: 尺子 digest 与写入时一致
- **WHEN** 消费者读本域尺子列表，并与某条记录该尺子的结论比对 digest
- **THEN** 两者逐字节相等
