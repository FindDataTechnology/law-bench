## Why

每条产品线都长出了自己的「自动修正 / 自动迭代」闭环，也各自长出了一把尺子、一道门和一套裁决词汇：合同走 all-pass 二值，技能/人格走两臂盲评「不劣于」，检索走相对降幅拦截，判官走分层校准门，爬虫自愈走 golden 重放全绿，柏讯数据集走规则求值。**六种门，六种词汇，六个互不相认的落点**（`eval_runs` / `eval_report` JSON / 工单 PR / 覆盖报告），于是一行评测结论**结构上无法与另一行的结论放进同一张图**。

后果有三个，正对应我们要解决的三件事：

- **改了之后变好没有，说不清**。一条结论不指名它跟谁比，所以「这次全过」和「上次全过」除了时间戳没有区别；「跑了一遍绿了」被当成「变好了」。
- **复核不了**。复核者拿不到「这次用的是哪把尺子的哪一版」，也就无法重跑复现；尺子自己改了之后，新旧分数被当成同一件事。
- **主人看不到全局**。没有一张跨线的评测台账，自动迭代在每条线内部空转，主人只能读六份口径不同的报告自己拼。

这个缺口已经卡住真实工作：`add-fleet-execution-loop` 让舰队成为可回写的执行方，`add-bench-ops-tools` 给了回写通道，但舰队回写的是**运行台账**，不是**评测结论**——「按知验台的尺子自评」这件事今天做不到，因为「当前生效的 rubric」是一个会变的视图，昨天与今天的分数不可比。

## What Changes

- **一条统一的评测记录（verdict）**：每条评测结论 SHALL 携带被评对象地址（`subject`：kind + key + version）、尺子地址（`ruler`：kind + key + digest）、通道（复用既有 `text`/`data`/`meta`）、门（四选一）、三态结局（`pass` / `fail` / `inconclusive`）、**baseline 引用**（或显式「无可比历史」）与逐条证据。落在既有 `eval_runs` 之上——**加列不换表**，历史行语义零变化。
- **四道门收成一个词汇表**：`no-worse`（候选不劣于对照）、`regression`（相对基线降幅超阈值即拦）、`all-pass`（逐条全过）、`calibrated`（尺子/判官自身可信）。各线保住自己的判定实现，只把**输出形状**收齐。
- **三态结局是硬要求**：样本不足、车道不通、判官不可达 SHALL 记 `inconclusive`，MUST NOT 折成 `fail` 或 `pass`。今天三条线各写一遍这条纪律（技能「评测没跑成≠通过」、蓝图试跑 `insufficient-evidence`、验收读数「判不出≠违规」），收成一个词。
- **尺子 digest 不同即不可比**：一条 verdict 的 ruler digest 与其 baseline 不一致时，SHALL 显式标记「口径已迁移」并拒绝以旧分数作对照，MUST NOT 发明换算系数。
- **未过校准门的判官产出 provisional 结论**：判官自身未通过分层校准门时，其 verdict SHALL 标 `provisional`，SHALL NOT 单独构成晋升依据。现行判官 4.1 尚未销账（无候选 balanced accuracy ≥0.70），此条不是假设性防御。
- **晋升后强制复测**：任一晋升/发版动作 SHALL 产出一条待复测的 subject 排队项；复测 verdict SHALL 引用晋升前的 baseline。闭环今天是断在末尾的——评测→提案→人批→新版本之后就结束了，「这个改动有没有用」永远没有答案。
- **运行台账与评测结论互链**：舰队/内核的运行回写产生评测时，运行记录 SHALL 可指到它产出的 verdict。

## Capabilities

### New Capabilities

- `eval-verdict-ledger`: 评测结论的统一台账契约——subject/ruler 地址、四道门词汇表、三态结局、baseline 可比性与口径迁移标记、provisional 标记、晋升后复测排队、逐条证据与原件引用，以及「记录只存结论、原件留本线」的边界。

### Modified Capabilities

- `bench-platform`: 「双通道评测」由「两条通道共用同一套运行记录」扩展为「每条运行记录 SHALL 携带 subject 与 ruler 身份」；「meta-eval」的校准运行 SHALL 落 ruler digest 并可作为 `calibrated` 门的一条 verdict。
- `domain-run-ledger`: 运行台账行在产生评测时 SHALL 可指到其产出的 verdict（互链，不复制结论）。
- `judge-channel-selection`: 校准跑 SHALL 以 verdict 形态落库（gate=`calibrated`、ruler=gold 集 digest），使判官可信度与业务评测共用同一台趋势机器。

## Impact

- **代码（law-bench-internal）**：
  - `src/eval/store.py`：`eval_runs` 增量列 `subject_kind` / `subject_key` / `subject_version` / `ruler_kind` / `ruler_key` / `ruler_digest` / `gate` / `outcome` / `baseline_run_id` / `provisional`（沿用既有 `_ADDITIVE_COLUMNS` 的 `ADD COLUMN IF NOT EXISTS` 纪律），`store_result()` 增可选形参；`outcome` 由既有 `all_pass` 回填历史行。
  - `src/bench/verdicts.py`（新）：门词汇表、三态判定、baseline 可比性与口径迁移判定、provisional 判定、晋升后复测排队项——纯函数 + 一处写入，不新增第二套评测实现。
  - `src/bench/calibration.py`：校准落行为 verdict 形态（ruler = gold 集 digest）。
  - `src/bench/agent_runs.py` / `domain-run-ledger` 写入路径：增 verdict 互链列。
- **对外契约**：`add-bench-ops-tools`（paas）的 `bench_run_report` 入参需扩展携带 ruler digest 与 gate；该扩展属 paas 伴随 change，本 change 只定 bench 侧接收形状。
- **依赖**：
  - `add-typed-publications`（已规划未落地）——ruler 的可拉取原件与 digest 唯一实现。B（可复核）的「凭 digest 取回原件」依赖它；本 change 不重复实现发布面，只消费其 digest。
  - `add-fleet-execution-loop`（已归档）——舰队回写面。
- **既有行为**：六条线各自的判定实现、门、阈值零改动；`eval_report` / 工单 / 覆盖报告等本地原件保留在原处，本 change 只要求回写结论行。
- **风险**：为 `eval_runs` 增列会让所有既有读写路径经一次性的 schema 迁移。缓解：全部列为可空或带默认值，legacy 行读出来的行为与迁移前逐字节等价（沿 `channel`/`unit_kind` 增列时的先例）。
