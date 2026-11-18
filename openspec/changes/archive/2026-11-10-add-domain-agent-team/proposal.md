# 域智能体团队（Domain Agent Team）

> 蓝图台账 **C7**。前序：C5 `add-domain-first-workbench`（域控制台/提案箱/派单）、C6 `add-corpus-document-adoption`（大库取材）。

## Why

平台的自动化接口已经齐了，但**没有团队**，而瓶颈已经量出来了（2026-11-10 生产实测）：

- **派单接口空转**：`authoring_tasks` 有状态机（`pending → in_progress → done/cancelled` + `transitions` 轨迹）、`dispatch` 能按缺口幂等派单，但生产上 **`tasks = 0`** —— 一次都没被用过。缺口矩阵因此只能"看见"，不能"流转"。
- **复核队列已在积压**：**48 条 pending** 提案，全部来自一个抽取岗，平均压了 4.0 小时、最老 12.1 小时；其中 **3 条（`受贿`/`行政许可`/`和解协议`）的键已经在库里** —— 这三条连"要不要写"都不用判断，纯粹是占用人眼的噪声。
- **绿灯会被体量骗**：`legal` 有 1,923 条条款却只有 15 个概念，其中只有 6 个有 `defines` 接地（40%）；`gov` 有 31 条单位但**证据率只有 45%**（14/31，机关与关系单位不带依据）。而四柱判据是"有没有"——灌量就能变绿。
- **两个会随团队自动长大的漏洞**：①提案幂等身份是 `(domain, source, external_key)`，**按提交方去重而不是按主张**——舰队岗与应用内团队同时上线时，同一主张会变成两行待确认；②`proposals.confirm` 的**自提自确认禁令对平台 `admin` 有豁免**（事件里写 `[admin-override]`），智能体一旦带 `admin` scope 就能给自己的提案签字。
- **没有运行台账**：长任务的唯一先例是 `admin.py` 的 daemon 线程，结局只进服务日志。要回答"昨晚智能体做了什么、花了多少、成没成"，只能翻 pod 日志。

结论：**不是让智能体更自主，而是把"谁做什么、被什么闸拦住、凭什么算干完"写死成契约，并且先建只读的巡检/质检，再放确定性写入，判断类永远只提案。**

## What Changes

1. **岗位契约（七机一人）**：取材员、结构员、概念员、质检员、评测员、发布员、巡检员各有一份输入/产出/闸门契约；值班长是 `lead` 角色的人，唯一持 `confirm` 权。岗位参数进 pack（与 `entity_keys`、`ingest_rule` 同思路），加一条线不改编排器。
2. **权限矩阵 + 硬停清单**：每个岗位能做什么写进契约；`confirm`、开域/归档、放宽订阅、改模板版本、删单位、铸凭据对所有智能体**一律禁止**。
3. **智能体身份按域成员治理**：`agent:<role>@<domain>` 必须是该域 `domain_members` 里 `role=expert` 的普通成员，**不带 `admin`/`*`**；代码层加一道——`submitted_by` 以 `agent:` 开头时 `admin-override` 一律 403。
4. **运行台账**：每轮跑留一行（岗位/域/任务/输入摘要/计数/结局/产物引用），结局四态 `ok | thin | failed | stopped`；只有一类允许重试。
5. **质量比进矩阵**：接地率、证据率、参照完整、覆盖度、评审时滞、判官健康——六项全部从库里反算，不需要智能体自评；缺口是否"关上"不再只看 `count > 0`。
6. **跨生产者去重**：提案去重身份从 `(domain, source, external_key)` 挪到 `(domain, 规范化 key)`，`source` 变成列表；同一主张的多个生产者合并为一行并显式标注。
7. **键归名下沉到写入边界**：现在只有 `corpus_catalog` 与 `extraction` 两个调用方归名，`authoring_create_unit` / 提案确认 / 批量导入都原样落库——写入方一多（舰队 + 七个岗位），"忘了 import pack"就会变成常态。交由内核在写边界统一归名。
8. **评审按批**：提案方必须交批摘要（共同主张 / 与现有单位的冲突 / 自己没把握的项）；人按批决策，机器先把不值得人看的部分拿掉并说明依据。

## Capabilities

### New Capabilities

- `domain-agent-team`: 智能体岗位契约、权限矩阵与硬停清单、智能体身份治理（域成员而非 admin）、职责分离（质检员输入白名单）、以及"事实可闭环 / 判断须人签"的分界。
- `domain-run-ledger`: 每轮运行的台账——四态结局、输入摘要、计数与产物引用；`thin` 与 `failed` 必须可区分，前者升级给人、后者不得用重试掩盖。
- `domain-quality-metrics`: 六个可复算的质量比（接地率/证据率/参照完整/覆盖度/评审时滞/判官健康），以及"缺柱消失不等于质量达标"的判据。

### Modified Capabilities

- `domain-estate-console`: 缺口矩阵除四柱状态外 SHALL 给出上述质量比；派单 SHALL 能针对"最薄的比率"而不是只针对空柱。
- `domain-team-runtime`: 执行面是壹座（每岗位一个 pack agent，persona 收窄工具面），权限由**工具是否存在**兜底；节奏由平台定时任务承载；每回合工具调用可追溯；无容器主机的原生自启。
- `domain-team-memory`: 记忆面是永忆——捕获在 **MCP 服务端担保**（不靠 agent 自觉）、三层各司其职、按（域, 岗位）隔离、且**记忆是顾问不是权威**。
- `ontology-key-scheme`: 归名下沉到写入边界——内核落单位与收提案时 SHALL 用该域注册的规则归名；未归名的键不得原样写入（原写法记 `aliases`）。现状是五个写入方只有两个（取目录、抽取）记得归名。

## Impact

- 执行面：windows-admin（tailnet 100.64.0.5）上的壹座实例（账号 aloadtree@gmail.com）；该机**无容器运行时**、系统盘余量紧张，两个服务按原生进程 + 计划任务自启，装到余量充足的盘。
- 记忆面：同机自托管的永忆（`fd-memory serve`，SQLite+FTS，无外部依赖），命名空间按（域, 岗位）。
- 代码：`src/bench/dispatch.py`（派单目标从"空柱"扩到"薄比率"）、`src/bench/estate.py`（质量比投影）、`src/bench/proposals.py` + `workspace_store.py`（去重身份与 agent 身份闸）、新增 `src/bench/agent_team.py`（岗位注册表读取 + 运行台账）、`src/web/routes/console.py`（值班长视图与台账入口）。
- 数据：`domain_proposals` 增加去重口径（迁移既有 pending 行需一次性合并）；新增运行台账表；`domain_members` 增加智能体成员（`agent:` 前缀）。
- 不改：内核写入路径（`authoring_*`）、键方案、模板词表、分发契约、检索路径。
- 风险：评审权若下放给机器，发布快照的对外承诺（digest 双侧一致、不可改写）会变成"机器说它没问题"——因此本 change 明确把 `confirm` 留给人类 `lead`；智能体的加速在**评审单位（批）与摘要**，不在签字人身份。
