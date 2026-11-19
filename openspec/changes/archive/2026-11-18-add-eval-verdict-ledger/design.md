## Context

动机见 `proposal.md`。设计只需知道三件既有事实：

1. `eval_runs`（`src/eval/store.py`）已经是事实上的统一落点——文本通道、数据通道（`channel='data'`）、校准 meta 行（`channel='meta'`）都写这里，且已有一套成熟的**增量列**纪律（`_ADDITIVE_COLUMNS` 里一串 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`，每次增列都保证 legacy 行与 legacy 写入路径逐字节等价）。所以本 change 不需要新表。
2. 尺子的规范 digest 实现只有一份：`src/bench/distribution.py::canonical_digest()`（键序归一、排除时间戳）。`add-typed-publications` 已规划把 rubric/gold 也纳入同一 digest 内核，但**那条 change 尚未落地**。
3. 各线已有的门各自成立，且都带一条自己的「判不出」纪律：`server/skill-eval.js` 抛错即 `markUnevaluated`、`blueprint-judge.js` 三态含 `insufficient-evidence`、`fleet-acceptance-readings` 要求「判不出」非零退出。它们缺的不是判定，是**共同的词汇**。

## Goals / Non-Goals

**Goals**

- 让两条来自不同产品线的结论能**放进同一张按对象聚合的趋势图**。
- 让「这次比上次好」成为一条可机械判定的性质（基线 + 同 digest），而不是一次解读。
- 让「判不出来」在记录层就与「判失败」分开，从而无法被晋升闸误放行。
- 在不新增表、不改任何既有门实现的前提下达成以上三点。

**Non-Goals**

- 不实现 rubric/gold 的发布面与拉取面（归 `add-typed-publications`）；本 change 只消费 digest。
- 不建壹座侧读面（另一个 change）。
- 不做跨 digest 的分数换算、不做跨对象排名、不做权重。
- 不把本地原件（报告 JSON、工单、覆盖报告）迁入本台账。

## Decisions

### D1 — 在 `eval_runs` 上增列，不建新表

**做法**：`eval_runs` 增可空列 `subject_kind` / `subject_key` / `subject_version` / `ruler_kind` / `ruler_key` / `ruler_digest` / `gate` / `outcome` / `baseline_run_id` / `provisional`；用既有 `_ADDITIVE_COLUMNS` 的 `ADD COLUMN IF NOT EXISTS` 一次性加。

**理由**：`eval_runs` 已经承载三条通道，且 `compare` / `list_runs` / 域归属 JOIN（`rubric_domain_id`）全都建在它上面。另建 `verdicts` 表意味着 `store_result()` 一个动作要写两处，两处必然漂移——那正是本 change 要消除的病。增列后 `outcome` 由既有 `all_pass` 回填（`all_pass=1 → pass`，否则 `fail`；历史行没有「无结论」的语义，不伪造），legacy 读取路径不改。

**考虑过的替代**：独立 `verdicts` 表 + 视图；否决理由是双写。给 `eval_runs` 改名；否决理由是已有生产消费方按表名读取。

### D2 — `outcome` 三态与 `all_pass` 并存，`all_pass` 降为诊断

`all_pass` 是 0/1 的历史契约，大量代码与展示依赖它。本 change 不动它，只新增 `outcome`。读面一律读 `outcome`；写面在未显式给 `outcome` 时按 `all_pass` 推导，显式给 `inconclusive` 时不看 `all_pass`。

这样「无结论」在数据库里就有一席之地，且**旧行永不出现 `inconclusive`**——它是新语义，不回溯。

### D3 — 门词汇表放在 `src/bench/verdicts.py`，作为闭集常量 + 一个纯函数

四道门是闭集，写入时校验；校验函数是纯函数（无 DB、无 LLM），便于单测且可被所有写入路径复用。这里刻意**不定义门的判定逻辑**——`no-worse` 在 paas 的 `skill-eval.js` 里怎么算，`regression` 在检索脚本里阈值多少，本模块一概不知，只校验标签合法性。

理由：一旦本模块开始「帮各线判定」，六条线就要来改这里，本 change 三个月内会变成一个需要协调六个仓的巨型 change。收窄成词汇表，各线零协调。

### D4 — baseline 是自引用外键，可比性靠 digest 相等

`baseline_run_id` 自引用 `eval_runs(id)`，可空（空 = 立基线）。可比性判定 = `baseline.ruler_digest == self.ruler_digest`。不等则标记口径迁移且不参与差值计算。

**考虑过的替代**：存「基线快照」副本以便日后对照；否决理由是不可变快照的职责属于发布面（`add-typed-publications`），台账再存一份分数字段就是第二权威源。

选外键而非「按 (subject, ruler) 自动找上一个」：自动找会让读取变成一次隐式查询，且「上一次」到底是哪一次在并发下不确定；显式引用让写入方为对照关系负责。

### D5 — provisional 由校准结论推导，不设配置位

判官是否可信，答案来自其最近一条 `calibrated` 门结论的 `outcome`；无此类结论 = 未校准。这与 `bench-platform` 既有「判官未经校准不得作 gold 信号源」一脉相承，并且天然消灭了「配置说已校准、实际没有」这种漂移。

代价：校准结论一旦过期（比如 gold 集换了 digest），判官会自动退回未校准。这是**期望行为**——换尺子之后旧的校准不能算数。

### D6 — 晋升后复测项是队列项，不是自动任务

晋升/发版动作产生一条待复测项（对象地址 + 基线引用），存 `local` 侧的待办（复用既有工单/提案机制之一，见 tasks 中的选择），MUST NOT 自动触发评测执行。

理由：评测是要花钱的（判官车道、人工 gold），自动触发会让一次晋升变成本不受控的成本。`fleet-owner-iteration` 已经定过「跟新只提示不迁移」，同一条纪律。

### D7 — 运行台账互链不加新表

`domain_agent_runs`（`src/bench/agent_runs.py`）增可空列存结论 id 数组，或存一个 `verdict_run_key` 关联。选**数组列**（`JSONB`），因为一轮运行可以产出多条结论（多个 KU 各一条），一对多。

## Risks / Trade-offs

- **[增列让所有写入路径过 schema 迁移]** → 全部列可空或带默认值；沿用 `channel`/`unit_kind` 增列时的同款做法，已有回归测试（全量 1895+）覆盖 legacy 行为等价。
- **[六条线接入是六次跨仓改动，可能半途而废]** → 分期：本 change 只要求**两条线**（合同 all-pass + 技能 no-worse）真正接上并跑出可比图，其余六条在 tasks 里列为可选后续。两条线跑通即证明记录形状可用。
- **[provisional 机制让大量结论「不足以晋升」]** → 这是事实而非故障：判官 4.1 本来就没销账。读面必须如实呈现，不得为了「好看」把 provisional 去掉。
- **[baseline 外键在数据清理时可能悬空]** → `eval_runs` 目前无删除路径（历史不删）；若未来引入归档，需同时处理 `baseline_run_id` 的悬空语义（读面已按「基线缺失 = 不可比」处理）。
- **[ruler digest 依赖 `add-typed-publications`]** → 在它落地前，尺子 digest 按 `canonical_digest()` 直接对当前 rubric 内容计算（同一份实现，只是尚未发布为不可变版本）。这样本 change 不阻塞，且落地后自动一致。

## Migration Plan

1. 增列（可空）→ 部署 → 新写入路径开始填新列，旧行为不变。
2. 回填 `outcome`（历史行按 `all_pass` 推导）→ 一条幂等 UPDATE。
3. 接入两条线 → 观察一轮真实评测产出可比图。
4. 回滚：列可空，回滚只需停止写新列，不丢数据；`outcome` 回填可逆（置空）。

## Open Questions

无。评审时若发现「待复测项存哪儿」（D6 的落点）需要提前定，可在 apply 阶段按既有机制最先可用者定，不改变任何规格。
