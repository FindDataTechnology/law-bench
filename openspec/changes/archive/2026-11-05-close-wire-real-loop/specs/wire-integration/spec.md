## Purpose

知验台（law-bench bench-platform）与柏讯（fd-wire）之间的真实数据循环契约：内部连接器以凭据双模（机器读/console 写）拉取 wire 真实本体、经升格流水线产 gold、按 wire 契约如实回写；并对散落评测尺子的 live 双跑裁决提供流程约束。本能力管「真实性判据与失败纪律」——每一步要么真跑成功留证，要么如实报失败不误标，永无假绿。

## ADDED Requirements

### Requirement: 凭据双模择路

连接器 SHALL 支持两种凭据模式并按端点自动择路：

- **机器模式**：`X-Internal-Token`（wire `add-entity-bench-contract` 交付的只读镜像面），用于持续同步读面；客户 scope 由部署配置钉死；
- **console 模式**：操作员 Logto ID token（env 注入），用于实体/关系写面与机器通道不可用时的读面回退；
- 择路规则：读面机器凭据可用即走机器通道，否则 console；写面无论凭据为何恒走 console 面；
- 凭据 SHALL 只经 env/注入进入进程，永不落仓、永不进日志（值脱敏）。

#### Scenario: 读面自动择机器通道
- **WHEN** 机器凭据与 console 凭据同时配置且执行同步
- **THEN** 读面请求走机器镜像面；写面请求（若有）走 console 面

#### Scenario: 缺凭据如实报错不触网
- **WHEN** 任何模式所需凭据缺失
- **THEN** 客户端启动即报可行动错误（指明缺哪个 env），零网络请求

#### Scenario: 凭据不落盘不进日志
- **WHEN** 连接器运行（含失败路径）并产出日志/错误信息
- **THEN** 日志与错误中无 token 明文；仓内零凭据文件（CI 泄露扫描持续拦截）

### Requirement: 真实同步幂等

真实拉取 SHALL 满足与 hermetic 链相同的幂等判据：同步后知验台侧身份键与 wire 全等（wire 为唯一身份主键源，零第二份身份存储）；重复同步零新增行、unchanged 不 bump 更新时间。

#### Scenario: 首次真实拉取
- **WHEN** 对 scope 客户（drillcust001）执行 `sync_now()`
- **THEN** wire 图谱节点/边入库，身份键与 wire 逐条全等，同步报告（created/updated/unchanged）留档

#### Scenario: 重复同步零漂移
- **WHEN** 紧接重跑 `sync_now()`
- **THEN** created/updated 为空集，unchanged 覆盖全量，无新增行

### Requirement: 真实升格与回写闭环

真实实体 SHALL 走升格流水线（bronze 机器预标注 → silver → gold 人工核验）且 gold 单元真实回写 wire：

- 回写实体经 wire 一等 `tier`/`sensitivity` 字段；关系经 wire 关系更新面（结构性字段不可变）；
- 回写幂等键=wire 实体键：重复 `run_writeback` 默认跳过已回写单元，不产生第二次推送；
- **如实失败纪律**：回写失败（网络断、422 漂移、凭据失效）时单元状态保持「未回写」+ 错误原因入库，批次其余单元照跑，任何路径不得误标「已回写」；
- 回写范围 SHALL 仅限 bench 已升格 gold 且带审核人留痕的单元（提案纪律：不触碰 wire 无关数据）。

#### Scenario: gold 实体真实回写
- **WHEN** 真实抽样实体经人工核验升格 gold 后执行 `run_writeback`
- **THEN** wire 实体 tier/sensitivity 一等字段就位，回执入库，单元标「已回写」

#### Scenario: gold 关系真实回写
- **WHEN** gold 关系单元执行回写
- **THEN** 走关系更新面更新 label/tier/sensitivity，不再出现「删除+重声明」或拒绝路径

#### Scenario: 回写失败如实
- **WHEN** 回写中途网络断或 wire 返回 422（数据集漂移）
- **THEN** 该单元保持「未回写」+ 错误原因入库，批次其余照跑；重跑按幂等键跳过已成功单元

### Requirement: 评测尺子 live 双跑裁决

对内核迁入的原仓尺子（市场发布门等），live 双跑 SHALL 以生产真实条目为输入，产出与原逻辑逐值对比的裁决记录：一致则迁入判据收账；不一致则逐例归因并给出决策（修内核对齐/保留 fail-closed 并记录偏差理由），不留悬置的 NOT EQUIVALENT。

#### Scenario: 发布门 live 双跑
- **WHEN** 对生产 paas registry 真实条目同时运行原发布门逻辑与内核迁入版
- **THEN** 逐条目决策对比记录留档（一致数/分歧数/每分歧例的归因）

#### Scenario: 分歧显式裁决
- **WHEN** live 双跑存在决策分歧
- **THEN** 每分歧例记录「原逻辑行为/内核行为/采纳方与理由」，无悬置未裁决项
