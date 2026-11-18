## Context

`add-finetune-data-flywheel` 已落地的只读抽取覆盖 6 张表（`clauses`/`pipeline_runs`/`eval_runs`/`eval_criteria_results`/`rubrics`/`criteria`）， bronze/silver 守卫、飞轮闸门、四元组/配对 schema 校验器均已跑通。活库盘点暴露三个具体问题：

1. **飞轮闸门关闭**：Judge-C gold = 0，Drafter reward modeling 无法启动。闸门本身正确——问题是没有产 gold 的路径。
2. **275 条 `type_validations` 规则未抽取**：其中 258 条含显式 `law_ref`（如「民法典§584、§585」），本质是**已带法律依据的合规准则脚手架**，却从未进入物料池。
3. **银牌配对重复率高**：363 条非空 `filled_text` 仅 151 条 distinct，~59% 重复。
4. **`law_info`（86 行）是 LLM 生成的法条摘要**（doubao/deepseek 各半），不是权威法条原文——此前「法条原文从哪拉」的开放问题有了答案：不能从这拉，只能当检索提示。

本设计在不破坏既有守卫/闸门/分层模型的前提下，把抽取面扩到 11 张表、把银池去重、并用 `type_validations × clauses × law_info` 搭一条**候选四元组脚手架**产线——人工核验后晋金，从而打开闸门。动机见 `proposal.md`；需求见 `specs/finetune-data-sources/spec.md`。

## Goals / Non-Goals

**Goals:**
- 把只读抽取从 6 张表扩到 11 张表，新增 5 张表的物料按互斥分层标签路由（`type_validations`/`core_clauses`/`industry_standard_references` → gold 脚手架原料；`contract_artifacts` → raw；`law_info` → bronze）。
- 在 Drafter-A 银牌导出时按 `filled_text` 正文去重，产出 151 条 distinct 配对，并留下「去重前/后」审计数字。
- 提供一条**候选四元组脚手架构建器**：按 `contract_type` 把 `type_validations` 规则（含 `law_ref` + `message`）与同类型的 `clauses` 正文 + `law_info` 法条摘要配对，产出 `tier: silver` 候选，供人工核验晋金。
- 所有新物料经既有 `common.py::assert_not_ground_truth` 单点守卫；机器脚手架永不自动晋金。
- 保持抽取的只读、幂等、零写既有表性质。

**Non-Goals:**
- 不做人工标注本身——构建器只产 silver 候选，人工核验晋金属后续运营（与 `add-finetune-data-flywheel` task 5.4 同一性质）。
- 不改既有 6 张表的抽取逻辑、schema、守卫或闸门。
- 不引入法条原文权威库（`law_info` 仅作检索提示；权威法条待人工标注时填入或后续 `industry-standard-reference` 变更接入）。
- 不放开开源许可证白名单（仍只 Apache-2.0/MIT）。
- 不补 22 个零-pipeline 类型的起草盲区（记录为已知缺口，不在本变更处理）。

## Decisions

### D1 — 新表分层标签按「来源权威性 + 用途」互斥指定

| 表 | 行数 | 分层 | 理由 |
|---|---|---|---|
| `type_validations` | 275 | `gold`（脚手架原料） | 含 `law_ref` 与 `message`，本质是人工/系统沉淀的合规准则；但**未经验证前不能直接当 gold 四元组**——构建器把它当原料产 silver 候选，人工核验后才晋金。 |
| `core_clauses` | 22 | `gold` | 强制条款清单，无 LLM 生成成分。 |
| `industry_standard_references` | 22 | `gold` | 成文法指针，无 LLM 生成成分。 |
| `contract_artifacts` | 362 | `raw` | 含 `{{slot}}` 的起草骨架模板，比 `pipeline_runs.filled_text` 干净但无标签语义。 |
| `law_info` | 86 | `bronze` | doubao/deepseek 两个 LLM 来源生成的法条摘要，**非权威法条原文**。 |

`type_validations` 的「gold 原料 → silver 候选 → 人工晋金」路径是关键设计：规则本身是 gold 级别的准则（含法律依据），但**配对后的四元组**在未经人工核验前只能标 silver——这与既有「机器产出永不自动 gold」的守卫一致。

- **替代**：把 `type_validations` 直接标 silver。否决——会丢掉「这些规则本身含法律依据、是高质量准则」的信号，且与 `core_clauses`/`industry_standard_references` 的分层不一致。
- **替代**：把 `law_info` 标 silver 供检索。否决——LLM 生成的法条摘要可能含幻觉，必须 bronze（永不作 ground truth），构建器引用时显式标 `legal_base.source: law_info:<llm_source>` 以溯源。

### D2 — 银牌去重在导出器 `_build_silver_pairs` 内按 `filled_text` 字节哈希去重

去重键 = ` hashlib.sha256(filled_text.encode("utf-8")).hexdigest()`；相同正文保留**第一条**（按 `pipeline_runs.id` 升序），丢弃后续。审计数字（去重前 N / 去重后 M）写入导出日志与 `data/finetune/manifests/warehouse_manifest.jsonl` 的元信息段。

- **替代**：按 `(contract_type, task_desc)` 去重。否决——同一 task 可能有合法多版本（不同 stance/iteration），按正文去重才精确。
- **替代**：模糊去重（编辑距离）。否决——引入非确定性，破坏幂等；字节哈希保证同输入同输出。

### D3 — 候选四元组脚手架构建器作为 `export_dataset.py` 的新子命令

`python scripts/finetune/export_dataset.py judge-c-scaffold` 输出 `data/finetune/judge-c/judge_c_scaffold.jsonl`：

1. 按 `contract_type` 分组 `type_validations`（仅含 `law_ref` 非空者，258 条）。
2. 对每条规则，取同 `contract_type` 的 `clauses` 正文（按 `section` 匹配规则的 `field`，无精确匹配则取该类型全部条款作候选池）。
3. `legal_base.text` 取规则的 `law_ref`；`legal_base.source` 标 `type_validations:<contract_type>:<constraint_id>`；若需补充法条摘要文本，从 `law_info`（同 `contract_type`）检索，引用时 `legal_base.source` 追加 `+law_info:<llm_source>`。
4. `clause_text` 取条款正文。
5. `verdict` 默认 `fail`（规则存在 = 该约束曾被触发/关注，候选默认「待核验是否违反」）。
6. `reasoning.justification` 取规则的 `message`；`reasoning.citation` 取 `law_ref` 拆分后的法条列表。
7. 每条候选标 `tier: silver`、`provenance: scaffold:machine:type_validations:<contract_type>:<constraint_id>`、`annotated_by: machine_self_eval`。
8. 过 `quadruple.schema.json` 校验；不通过的丢弃并记入 `coverage_gaps.jsonl`。

构建器**不写** `judge_c_gold.jsonl`——gold 文件仅由人工核验产出经导出器校验后落盘（与既有流程一致）。

- **替代**：让构建器直接产 gold。否决——违反「机器产出永不自动 gold」守卫，且会绕过飞轮闸门的人工核验前提。
- **替代**：把 `verdict` 默认设 `pass`。否决——规则存在通常意味着该约束曾被触发/关注，默认 fail 更符合「待核验是否违反」的语义，且与既有「机器 pass → 强制降 fail」规则一致。

### D4 — 新表抽取扩展现有 `extract_warehouse.py` 的 `TABLES` 与 `TIER_BY_TABLE`

在 `scripts/finetune/common.py::TIER_BY_TABLE` 增补 5 条映射；`extract_warehouse.py::TABLES` 增补 5 条 SELECT。所有新 SELECT 仍是纯只读，复用既有 `dumps_record`/`write_jsonl`/`append_jsonl` 路径，幂等性由既有确定性 JSON 序列化保证。

新增表的 `provenance` 格式：
- `type_validations:<contract_type>:<constraint_id>`（复合键，因 `constraint_id` 仅在 `contract_type` 内唯一）
- `law_info:<id>`
- `contract_artifacts:<id>`
- `core_clauses:<id>`
- `industry_standard_references:<id>`

`warehouse_manifest.jsonl` 自动随既有 `append_jsonl` 路径追加新物料记录，无需单独处理。

### D5 — 人工核验晋金路径沿用既有 `export_dataset.py validate` + 文件落盘

人工核验产出形如 `data/finetune/judge-c/human_gold_batch_<date>.jsonl`，每条标 `tier: gold`、`annotated_by: human_annotated`、`reviewer: human`。导出器 `validate` 子命令校验每条过 `quadruple.schema.json`（含「`verdict=pass` 须 `reviewer=human` + `citation` 非空」规则），通过后追加到 `judge_c_gold.jsonl`。飞轮闸门在 `judge_c_gold.jsonl` 非空时放行——**本变更不修改闸门逻辑**，只通过产 gold 文件让闸门自然打开。

若人工核验采纳 `law_info` 中的法条表述，**必须**把 `legal_base.source` 改标为权威来源（如 `民法典§509`），不得保留 `law_info:<llm_source>` 作为 gold 的 `legal_base.source`——这条规则编码进 schema 注释与校验器提示。

## Risks / Trade-offs

- **[脚手架候选质量参差]** → `type_validations × clauses` 按 `contract_type` 配对，但 `field` 与 `section` 未必精确匹配，可能产出语义不相关的候选。缓解：构建器优先按 `field == section` 精确匹配，无匹配时降级到同类型全条款池并在候选中标 `match_type: fuzzy`，人工核验时可快速过滤。
- **[law_info 幻觉污染]** → 构建器若把 `law_info` 的 LLM 摘要填进 `legal_base.text`，可能引入不存在的法条。缓解：`law_info` 文本仅作检索提示，`legal_base.text` 主字段取规则的 `law_ref`（人工沉淀的权威引用）；引用 `law_info` 时显式标 `legal_base.source: law_info:<llm_source>`，且该候选永不晋金除非人工改标。
- **[silver 去重改变下游规模]** → 306 → 151 条会让 Drafter-A 暖启池缩水。缓解：151 是 distinct 正文数，质量高于 306（去掉了重复草稿）；SFT 暖启对 distinct 数更敏感而非对总量。
- **[type_validations 规则可能过时]** → 规则可能对应旧版法条。缓解：规则本身标 `tier: gold` 作脚手架原料是「这些准则曾被关注」的信号，不是「这些准则当前正确」的信号；人工核验环节负责校验法条时效性。
- **[新表抽取增加 pod 运行时间]** → 5 张新表（尤其 `contract_artifacts` 362 行含大文本）可能拉长抽取。缓解：均为小表，实测影响 < 30 秒；若成问题可后续加分表并发。
- **[构建器产出规模可能过大]** → 258 规则 × 同类型条款可能产出数千候选。缓解：构建器默认每规则取 top-1 条款（按 `field == section` 精确匹配），无匹配时降级到 top-3（按 `section` 在 `contract_type` 内的出现频次），候选总量控制在 ~500 条量级。

## Migration Plan

本变更是**纯增量扩展**，无迁移：
1. `common.py::TIER_BY_TABLE` 增补 5 条映射。
2. `extract_warehouse.py::TABLES` 增补 5 条 SELECT；重跑抽取，新表物料落入 `data/finetune/warehouse/`，`warehouse_manifest.jsonl` 自动追加。
3. `export_dataset.py::_build_silver_pairs` 增加 `filled_text` 哈希去重；重跑 Drafter-A 导出，审计数字写入日志。
4. `export_dataset.py` 增加 `judge-c-scaffold` 子命令；产出 `judge_c_scaffold.jsonl`（silver）。
5. `docs/finetune-data.md` 更新表/分层映射、银池真实规模（151）、`type_validations` 脚手架流程。

回滚：删除新增的 5 张表物料文件 + `judge_c_scaffold.jsonl` + 还原脚本改动；既有 6 张表物料与运行时零影响。

## Open Questions

- 脚手架构建器的 `field == section` 精确匹配命中率实际多少？—— 可在构建器首次运行时统计并记入审计日志，不阻塞本变更设计；若命中率过低，后续调整匹配策略（如按 `kind` 字段语义匹配）。
- 人工核验脚手架候选的 UI/工具？—— 不在本变更范围；运营侧可用任何 JSONL 编辑器，schema 校验器保证产出格式正确。
