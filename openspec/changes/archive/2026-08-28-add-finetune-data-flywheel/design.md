## Context

law-bench 已有一条跑通的「LLM 自产自评」链路：`generate → fill → evaluate → check → improve → store`，产物落在 `pipeline_runs`（548 条）与 `eval_runs`/`eval_criteria_results`（870 条），条款库 `clauses` 6686 条。这条链路的评估端用 `EVAL_MODEL`（kimi-k3）当 judge，`docs/evaluation-system.md` 已自认其「结构性误读」（混淆合同正文与评分项、在合同里索要 PASS/FAIL 标记），仓内 `all_pass` 仅 31% 即为活体证据。要给这条链路换上一个可信判官，并把起草端从「填槽草稿」升级到「合规正文」，就必须先有一层独立的数据准备子系统——它读这条链路的产物做**物料**，但不把机器自评当**标签**。

本设计覆盖该数据准备子系统的技术形态。动机见 `proposal.md - Why`；需求见 `specs/finetune-data-flywheel/spec.md`。

## Goals / Non-Goals

**Goals:**
- 一条**只读、幂等**的仓库抽取链路：从 `clauses`/`pipeline_runs`/`eval_runs`/`eval_criteria_results`/`rubrics`/`criteria` 导出原始训练物料，零写入既有表。
- 一个**许可证闸门**的开源接入层：只放行 Apache-2.0/MIT 语料入商业微调；AGPL/GPL 在接入层即被拒。
- 一套**分层 + 溯源**数据模型：金/银/铜/原料四层，每条物料带 `source`/`license`/`tier`/`provenance`，其中铜层（机器自评）被硬约束为「永不作 ground truth」。
- 两个**独立 schema 校验**的数据集：Judge-C 四元组 + Drafter-A 配对，前者须先于后者的 reward modeling 存在。
- 全流程**可复跑、可校验**：`openspec validate` 过；抽取脚本可幂等重跑；数据集 schema 可机器校验。

**Non-Goals:**
- 不做模型训练本身（只产数据）。
- 不改既有 `evaluation-rules`/`dual-evaluation`/`contract-drafting-pipeline` 的运行时行为。
- 不在本变更内修复 judge 的结构性误读（那是既有 judge 的事；本变更是在其**之上**建标注层，且人工标注规则专门防这个坑）。
- 不在本变更内补齐 ~22 个零-pipeline 类型与 custom 条款偏薄（267 条）的 curation——记录为已知缺口供后续。
- 不引入新的在线服务/MCP 工具；产出是离线数据集 + 抽取/接入脚本。

## Decisions

### D1 — 物料落盘为目录 + 溯源清单，不建新 DB 表
训练数据集以**文件目录**形态产出（`data/finetune/<dataset>/`），每条样本一个 JSONL 记录；另附一份**溯源清单**（CSV/JSONL，`source`/`license`/`tier`/`provenance`/`row_ref`）。不新建数据库表——既有六表够用，新增表会让「只读抽取」的边界变模糊。
- **替代**：新建 `finetune_samples` 表。否决——增加写面、与「只读」目标冲突，且离线数据集用文件更利于版本化与外部训练流水线消费。

### D2 — 四层（金/银/铜/原料）以 `tier` 字段硬标记，铜层加守卫
`tier ∈ {gold, silver, bronze, raw}`：
- `gold` = rubric+criteria（人工金牌）/ 人工核验合规正文 → 可直接作 ground truth / reward。
- `silver` = `pipeline_runs.filled_text`（LLM 草稿）→ 仅 SFT 暖启，不作 reward 标签。
- `bronze` = `eval_criteria_results.verdict/reasoning`（机器自评）→ **守卫：任何下游消费方取 bronze 物料作 ground-truth 标签时，抽取/导出器须报错拒绝**。
- `raw` = `clauses` 条款正文 → 结构骨干 + 判官输入池，无标签语义。
守卫在导出器一处实现（单点），而非散落在消费方。

### D3 — Judge-C 四元组 schema 用 JSON Schema 校验，标注规则编码进 schema 注释
四元组 `(legal_base, clause_text, verdict, reasoning)`：
- `legal_base` = {source, text}（如「民法典 第509条」+ 条文原文片段）。
- `clause_text` = {body, section}。
- `verdict` ∈ {pass, fail}。
- `reasoning` = {justification, citation[]}。
标注规则编码为 schema 约束 + 导出器校验：`reasoning.citation` 非空（每个 verdict 引用 ≥1 法条/规则）；`verdict=pass` 仅在 `provenance.reviewer = human` 时允许（机器自评即便判 pass 也强制降级为 fail）。

### D4 — 飞轮顺序以「数据集存在性闸门」强制，不靠文档约定
Drafter-A 的 reward/DPO 产出脚本在启动时**检查 Judge-C 数据集文件存在且非空**，否则拒绝运行。顺序约束从「写在 README 里」升级为「代码闸门」，避免后续误用。

### D5 — 仓库抽取复用已验证的 kubectl-exec + `psycopg.connect(database_url)` 模式
抽取脚本在 pod 内执行（`kubectl -n law-bench exec deployment/law-bench -- python ...`），复用 pod 环境里已存在的 `database_url`，凭证不外泄、不在脚本里硬编码。抽取为**纯 SELECT + 落盘**，零写入。

### D6 — 开源语料接入在接入层做许可证闸门，白名单硬编码
`license_allowlist = {Apache-2.0, MIT}`；接入器对每个候选语料读其 `LICENSE` 文件做字符串匹配，不在白名单的整包拒绝并记入拒绝清单（含拒绝原因）。AGPL-3.0（ChatLaw）/GPL-3.0+严禁商业（LaWGPT）因此被排除。白名单只放宽不改收紧，收紧须另起变更。

### D7 — Phase-1 标注种子按真实仓内数定标
Judge-C pilot 种子 = top-5 类型（sale 58 / employment 33 / property_service 27 / technology 23 / film_production 22）×100 ≈ 500 四元组；全 43 类铺开 ~4K。Drafter-A 银牌暖启池 = 548 条 `filled_text`。这些数字来自本次活库盘点，直接进 design 作为规模基准。

## Risks / Trade-offs

- **[铜层守卫可能被绕过]** → 守卫只在导出器一处实现（D2）。风险：有人直接读 `eval_criteria_results` 原表。缓解：在 `docs/finetune-data.md` 明写「原表 verdict 不可作标签」并在抽取器对 bronze 物料打醒目水印；根因治理要等后续修 judge。
- **[开源语料许可证误判]** → 接入器只做 `LICENSE` 字符串匹配，多协议/子条款可能漏判。缓解：白名单从严（仅 Apache-2.0/MIT 两类最宽松且明确商业可用），模糊包一律拒绝入库而非放行。
- **[四元组人工标注成本高]** → Phase-1 ~500 四元组仍需法务人力。缓解：先 pilot top-5 类型走通端到端，验证标注规范可行后再铺开；标注规范专门防 judge 的三个已知误判坑。
- **[silver 物料质量天花板低]** → `filled_text` 是 kimi-k3 草稿，含判官误判带偏的下游风险。缓解：silver 仅作 SFT 暖启不作 reward 标签（D2 已隔离）；金牌正文靠开源补 + 后期人工抽检。
- **[22 个零-pipeline 类型的起草盲区]** → 这些类有 base 条款但无 pipeline 样本，Drafter 在其上无银牌物料。缓解：记为已知缺口，不在本变更补；后续 curation 变更处理。
- **[飞轮顺序闸门过严可能卡住迭代]** → D4 要求 Judge-C 先存在。缓解：闸门只检查「文件存在且非空」，不要求规模达标；pilot 50 条即可放行 Drafter 暖启。

## Migration Plan

本变更是**纯增量、零迁移**：
1. 落 `data/finetune/` 目录结构 + 溯源清单格式。
2. 落仓库抽取脚本（只读 SELECT + 落盘），可随时重跑，不影响线上。
3. 落开源接入器（许可证闸门），离线运行。
4. 落四元组/配对 schema 校验器 + bronze 守卫 + 飞轮顺序闸门。
5. 人工标注按 top-5 类型 pilot，不在本变更的代码任务内（属后续运营）。
回滚：删除 `data/finetune/` 与新增脚本即可，既有表与运行时零影响。

## Open Questions

- 四元组 `legal_base` 的法条原文是否需要从 `law_refs`/`industry-standard-reference` spec 接的条文库拉取，还是标注时人工填入？—— 可在标注 pilot 阶段定，不阻塞 spec/任务拆分。
- 溯源清单最终用 CSV 还是 JSONL？—— 视下游训练流水线消费方而定，可后置；本变更先产出 JSONL。
