# bench-platform Specification

## Purpose
定义知验台（全域知识沉淀 × 评测平台）的内核行为契约：知识单元类型化、域包插拔、双通道评测、溯源四层守卫、meta-eval、柏讯实体升格契约与开源切分边界。内核领域无关，法律垂类是第一个域包。

## Requirements

### Requirement: 知识单元类型化

语料库的存储单元 SHALL 泛化为带 `kind` 的知识单元（如 clause/entity/relation/fact/indicator/qa-pair），clause 为第一个 kind 且存量条款数据零迁移语义变化；评测、复核、组装、微调导出的读写面 SHALL 按 kind 泛化并保持对既有 clause 行为逐字节等价（既有测试套件全绿且断言口径不变）。

#### Scenario: 新增 kind 不改内核
- **WHEN** 以新 kind（如 indicator）写入一条知识单元并对其发起评测
- **THEN** 语料库、评测运行、复核流程均接受该 kind，内核代码无需为该 kind 增改分支

#### Scenario: 法律垂类零回归
- **WHEN** 泛化重构合入后运行既有全量测试套件
- **THEN** 全部测试通过且断言口径与重构前一致，法律域既有行为（组装/评测/复核/导出）无可观测变化

### Requirement: 域包插拔接口

平台 SHALL 以域包（domain pack）承载领域资产：每域包声明其知识单元 kind 集、语料适配器、rubric 包、评测套件与（可选的）确定性校验器；内核 SHALL NOT 含任何领域专有逻辑或领域常量；新增一个领域 SHALL NOT 修改内核代码。法律域包的组件（条款种子、法规目录、引用核检）SHALL 全部迁入域包边界内。

#### Scenario: 新域包接入
- **WHEN** 以域包声明文件接入一个新领域（含语料适配器与 rubric 包）并注册
- **THEN** 该域的知识单元入库、评测与复核全链可用，且本次接入的变更集中不触碰 `src/bench`（内核）内任何文件

#### Scenario: 内核领域无关
- **WHEN** 在内核源码树中检索领域专有名词（合同类型、法条、法条引用等法律常量）
- **THEN** 命中仅存在于法律域包目录与其数据文件，内核源码零命中

### Requirement: 双通道评测

评测对象 SHALL 分两通道：文本对象（草稿/答案/报告/条款）走 LLM-judge × rubric × criteria 通道；数据对象（数据集/指标/图谱快照/AI 取数回答）走确定性校验通道（行数/期数/对账/漂移/基线比对，校验器由域包声明）。两通道 SHALL 共用同一套运行记录、compare、趋势与人工复核机器；每条评测记录 SHALL 如实标注其通道。

#### Scenario: 数据对象确定性评测
- **WHEN** 对一个数据对象（如某指标数据集的快照）发起评测，其域包声明了确定性校验器
- **THEN** 评测运行逐条执行校验器并落 per-check verdict（数值级对/错），不调用 LLM judge，限流与模型故障不影响其结果

#### Scenario: 数据 QA 金集评测 AI 用数
- **WHEN** 以数据 QA 金集（题目绑定真实数据集与期望结果）对 AI 取数/答数对象发起评测
- **THEN** 每题按期望结果判定正误并落可追溯记录（题目→数据集→期望→实际→verdict），可进入 compare 与趋势

#### Scenario: 通道如实标注
- **WHEN** 查询任一评测运行的记录
- **THEN** 记录含通道字段（text/data），下游聚合与展示按通道区分，不混淆

### Requirement: 溯源四层与真值守卫

知识单元与物料 SHALL 标注互斥四层 tier：gold（人工核验，可作 ground truth/reward）、silver（机器草稿，仅暖启）、bronze（机器自评，仅失败分析）、raw（无标签语义）；分层语义由加载器单点实现，过滤语义（如「silver 及以上」） SHALL 与现行 finetune 飞轮一致。bronze 与 silver SHALL 永不作 ground truth 或 reward——守卫 SHALL 在导出器单点实现，任何按真值用途取 bronze/silver 的请求即报错拒绝，绕过导出器直读原表 SHALL 被登记为已知风险并纳入文档与代码评审检查项。

#### Scenario: 真值守卫拒绝 bronze
- **WHEN** 下游脚本经导出器按 ground-truth/reward 用途请求 bronze 物料
- **THEN** 导出器报错拒绝并指明 tier 违规，不返回任何 bronze 行

#### Scenario: 分层互斥
- **WHEN** 任一物料尝试同时携带或写入两个 tier 值
- **THEN** 写入被拒绝（422 如实指明），存量数据无多值 tier

### Requirement: meta-eval（尺子的尺子）

平台 SHALL 对判官与评测套件本身做度量：judge 对 gold 的校准（按置信分档的准确率与单调性）与评测套件的漂移检测 SHALL 为一等运行记录，与被评对象共用趋势机器；判官校准结果 SHALL 随 judge 模型与提示词版本留痕。现行判官（all_pass 仅 31%、存在结构性误读）SHALL 作为第一个校准对象，其结构性误读修复前 SHALL NOT 被任何域包声明为可信 gold 信号源。

#### Scenario: judge 校准运行
- **WHEN** 对某 judge（模型+提示词版本）在指定 gold 集上发起校准运行
- **THEN** 产出按置信分档的准确率矩阵与单调性结论，落库可查，纳入该 judge 的版本档案

#### Scenario: 未校准判官受限
- **WHEN** 某域包尝试将未通过校准（或校准失败）的 judge 声明为 gold 信号源
- **THEN** 声明被拒绝并如实指明「judge 未通过校准」，不产生该域的 gold 标注

### Requirement: 柏讯实体升格契约

平台 SHALL 从 fd-wire entity-layer 读取实体/关系声明作为 **seed 升格原料**，按 raw→bronze→silver→gold 审核流升格；升格流水线 SHALL 保证：seed 阶段 wire 为原料身份的参照键（平台 KU 以 wire 源引用与 `external_key` 回指 seed），**已发布本体的权威源是平台**（平台经版本化发布面向全部消费者分发，wire 作为消费者拉取快照落本地自行处理）；gold 回写 wire 时 SHALL 附带 `sensitivity`/`tier` 标记（面向 seed 源的档位回写，供其 ACL 与舰队消费）；升格与回写全程 SHALL 可追溯（每条 gold 可回指 wire 源声明与审核人）；发布契约见 `knowledge-distribution`。

#### Scenario: 实体升格入库
- **WHEN** 同步 wire 实体声明并经机器预标注（bronze）与人工核验（gold）
- **THEN** 知验台产生带 wire 源引用的 gold 实体，seed 身份可回指 wire；平台发布的本体版本以该 gold 内容为权威形态

#### Scenario: gold 回写带档
- **WHEN** gold 实体/关系回写 wire
- **THEN** 回写载荷含 sensitivity/tier 标记，wire 侧 ACL 与舰队可直接消费；回写失败如实报错且知验台侧状态不误标「已回写」

#### Scenario: 发布权威源
- **WHEN** 消费者（含 wire）经分发面拉取平台已发布本体
- **THEN** 快照以平台发布版本为权威（digest 锚定），消费者本地处理不构成第二权威源；wire 本地存储与平台发布版本的分歧按消费者侧本地版本化处理（对账依 pull 面）

### Requirement: 开源切分边界

公共仓 SHALL 仅含内核、域包接口与法律域包；内部域包（柏讯连接器、内部语料、gold 数据集、客户数据）SHALL 存于内部仓（law-bench-internal）。公共仓 CI SHALL 增加泄露扫描：内部仓路径引用、凭据形态、客户数据样本 SHALL 令构建失败；公共仓文档中的能力宣称 SHALL 与公共仓实际可运行面一致。

#### Scenario: 泄露扫描拦截
- **WHEN** 公共仓某次提交引用内部域包路径、内嵌凭据或包含客户数据样本
- **THEN** CI 扫描失败并逐条指明违规文件与处置方式，不产出镜像

#### Scenario: 公共面宣称一致
- **WHEN** 公共仓 README 或文档宣称某能力
- **THEN** 该能力在公共仓内（或经其声明的公开依赖）可运行，内部仓专属能力须显式标注「内部」
