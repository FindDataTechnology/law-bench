## Why

知验台和壹座之间今天只有**一条单向线**：壹座舰队把本体草案提交进知验台的域提案箱（paas `switch-fleet-proposals-to-domain-inbox`，paas 侧 3.1–3.3 已落）。这条线只解决了「产物怎么进来」，没有解决其余三件事，而三件事都是同一个缺口的不同侧面——**知验台分不清谁是执行方，因此既派不出活，也记不清账，还退不回落**。

三个具体后果，都已在代码里坐实：

1. **派单是死胡同。** `src/bench/dispatch.py` 的 `GAP_OWNER` 只把缺口映射到内核自己的七个确定性岗位名，模块开头明写「Nothing here decides *who*」；`authoring_tasks.assignee` 是自由文本。界面上却写着「Owner / fleet」——用户以为能派给舰队，实际派给的是一个字符串，没有任何东西会送到壹座。质量缺口 → 派单 → 没有执行者。
2. **运行台账半盲。** `domain_agent_runs` 只有 `role / run_key / task_id / outcome / counts / remaining / artifact_refs`，**没有任何一列能说明这一轮是内核 Python 跑的，还是壹座舰队跑的**。而 `/d/{key}/team` 那页的「运行台账」正是查这张表——值班长看到的「谁在跑」永远只有内核那七个岗位，真正跑 LLM 的那些看不见。
3. **驳回结果不回流。** 驳回理由停在 `domain_proposal_events` 里；舰队唯一的发现方式是下一轮再提一次、被 `evidence_digest` 去重挡下，而「为什么被驳回」它读不到。

为什么现在做：域优先工作台（C5）已上产、域提案箱已收到真实草案、五岗舰队已在生产跑过五个岗位的实活，六条垂直线在排队开域。**再往后每多一条线，这个缺口就多一份**——同一条缺口内核岗和舰队岗都会去干，产物进同一个提案箱，两本台账各记一半，而没有任何机制能让它们收敛。

本 change 只画一条界并把它接成闭环：**确定性、可机械判定的活归内核岗位；需要判断、要 LLM 的活归舰队**。界画出来之后，派单就不再是死胡同（缺口分诊到内核岗或舰队工单），运行台账就不再半盲（同表按 `origin` 并列），驳回也就能回落到提交方。

## What Changes

- **派单升级为工单**：`authoring_tasks` 的指派人从自由文本升级为**类型化指派人**（人 / 内核岗位 / 已登记舰队），并新增工单的**认领**与**完成**语义。工单的创建、认领、完成都留事件，且「同一缺口已有未关闭工单不再重复创建」的既有收敛判据保持不变。
- **舰队成为可登记的提交方与执行方**：消费者登记增加 `kind`（机器拉取方 / 舰队），舰队登记携带 `fleet_ref`（如 `fleet:<fleet_id>`）与绑定域。提交来源 SHALL 按前缀分**四类**校验——`fleet:`（已登记、未吊销、绑定本域）、`extract:`（**仅限进程内**，外部端点一律拒绝，否则任何人都能自报为抽取流水线）、`agent:`（平台已铸身份且为该域活跃成员）、`user:`（交互式提交，只能以自己的身份）。未知前缀一律拒绝。这条同时把「同一份草案有两套账」的反面修掉：来源从此可反查是哪个舰队哪个岗位哪一轮。
- **运行台账分来源**：`domain_agent_runs` 增加 `origin`（`kernel` / `fleet`）与 `runner_ref`（外部执行方标识），外部回写以幂等键收敛、重放不新增行。内核岗位行为与既有四态语义**零变化**。
- **提案结果回流**：新增提交方可见的**提案结局读面**（按 `source` 拉取其提交过的提案及其确认/驳回结果与理由），使「被驳回后不得原样重提、换依据才能重新入箱」这条既有纪律对提交方可执行。
- **非目标（明确不做）**：不做「知验台直接调度壹座」（派单只到工单，执行由壹座自己的节奏决定）；不做知验台与壹座共库（松耦合铁律：两者之间只有 HTTP 契约）；不把 §7.2 的 paas 侧出口搬进本仓；不改内核七岗的确定性实现。

**BREAKING**：`POST /api/d/{domain_key}/proposals` 对 `source` 的校验从「任意字符串」收紧为「按前缀分四类、各查各的依据」，未通过者由 200/201 变为 403。2026-11-13 在产库实测：`domain_proposals` 93 行中 `extract:*` 78 行（进程内写，不受影响）、`fleet:*` 12 行（含 1 条探针，需人工登记或归 legacy）、`agent:*` 4 行（平台自铸身份，有效）。切版前须先完成 §Impact 的登记迁移，否则在跑的舰队提交会被拒。

## Capabilities

### New Capabilities

- `domain-work-order`: 工单的类型化指派人、认领与完成语义、提交方可见的拉取面、幂等与收敛判据，以及「确定性活归内核、需判断的活归舰队」的分诊规则。
- `fleet-submitter-contract`: 提交方契约的两个面——进来时的身份校验（按 `fleet:` / `extract:` / `agent:` / `user:` 四类分别施以凭据、调用位置、自铸身份、已认证会话四种依据；吊销即时失效；迁移宽松档留痕且不放宽冒充）与出去时的提案结局回流（按来源可读、驳回理由原文、换依据才可重提可判定）。

### Modified Capabilities

- `domain-run-ledger`: 运行记录增加来源（内核 / 舰队）与外部执行方标识；外部回写以幂等键收敛。既有四态、进度不变量与输入摘要语义不变。
- `knowledge-distribution`: 消费者登记增加 `kind` 与 `fleet_ref`，使舰队成为可校验的提交方/执行方而不只是拉取方；机器拉取面语义不变。
- `domain-estate-console`: 按缺口批量派单的指派目标从自由文本升级为类型化选择，并在界面上如实区分「派给内核岗位」与「派给舰队工单」。

## Impact

- **代码（law-bench-internal）**：
  - `src/bench/workspace_store.py`：`authoring_tasks` 增指派人类型与工单语义列、`distribution_consumers` 增 `kind`/`fleet_ref`、`domain_agent_runs` 增 `origin`/`runner_ref`（均走 `ensure_schema` 幂等建列）。
  - `src/bench/dispatch.py`、`src/bench/authoring.py`：指派人类型化与认领/完成转移。
  - `src/bench/agent_runs.py`：外部回写入口与 `origin` 投影（不改内核岗位调用点）。
  - `src/bench/proposals.py` 与 `src/web/routes/console.py`：提案结局读面与 `source` 校验。
  - `src/web/routes/console.py`：派单选人、工单可见、运行台账按来源分列。
  - 迁移：既有 `authoring_tasks.assignee` 与 `domain_proposals.source` 存量行不得改写为「未登记」；对已存在的 `fleet:*` 语义来源提供一次性登记或显式归入 `legacy` 的处理路径，并由 dry-run 给出计数。
- **外部依赖（paas）**：本 change 不实现 paas 侧客户端；但 `source` 收紧后，paas 侧必须先按登记值提交。落地顺序见 `openspec/program.md`（paas `add-bench-ops-tools` 与之并行）。
- **契约**：`docs/domain-proposal-contract.md` 的字段与错误码表随之更新，`tests/test_domain_proposal_contract_doc.py` 双向校验保持不漂。
- **风险**：`source` 收紧是有意的**破坏性收紧**——松着不改，来源就永远是注释而不是事实。回退路径是登记表加回宽松档，而不是删校验。
