## 1. 宽表只读抽取扩展

- [x] 1.1 在 `scripts/finetune/common.py` 的 `TIER_BY_TABLE` 增 5 张附加表分层：`type_validations`→gold、`core_clauses`→gold、`industry_standard_references`→gold、`contract_artifacts`→raw、`law_info`→bronze
- [x] 1.2 在 `scripts/finetune/extract_warehouse.py` 的 `TABLES` 增上述 5 张表，保持 `SELECT * FROM {table} ORDER BY id` 只读路径不变
- [x] 1.3 在 pod 内重跑 `extract_warehouse.py`，产出 11 张表 JSONL；行数对账 clauses=6686/pipeline_runs=548/eval_runs=924/eval_criteria_results=9134/rubrics=131/criteria=1275/type_validations=275/law_info=86/contract_artifacts=401/core_clauses=22/industry_standard_references=22（contract_artifacts 401，含 superseded 行，全量抽取正确）
- [x] 1.4 验证幂等：同库连跑两次，11 张表 JSONL 逐字节 md5 相同；SQL 全为 SELECT，既有表零写入

## 2. 新表分层路由与守卫

- [x] 2.1 验证附加表物料各带 `provenance`/`source: warehouse`/`tier`（law_info=bronze、contract_artifacts=raw、type_validations/core_clauses/industry_standard_references=gold）
- [x] 2.2 验证 `law_info`(bronze) 被 `filter_by_tier(floor='gold')` 排除在 ground-truth 外；`assert_not_ground_truth('bronze','ground_truth')` 抛 TierGuardError
- [x] 2.3 验证 `contract_artifacts`(raw) 不进入 gold/silver 输出集（filter_by_tier 只返 gold/silver）

## 3. 银牌配对去重

- [x] 3.1 在 `scripts/finetune/export_dataset.py` 的 `_build_silver_pairs` 按正文 sha256 去重（保留首条），并在去重**前**过槽位一致性（正文无残留 `{{slot}}`）+ `task_desc` 非空校验丢弃残稿，避免首条残稿阻塞其后合法副本
- [x] 3.2 审计：打印「去重前 N / distinct M / 校验通过 K」；实测 **356 非空 → 残稿过滤后 131 distinct**（proposal 估 363→151，数据漂移，以实测为准）；131/131 通过 `validate_pair`
- [x] 3.3 验证被保留配对的 `tier:silver`/`source:warehouse`/`provenance:pipeline_runs:<id>` 字段未因去重丢失
- [x] 3.4 验证去重后银牌池仍被 `load_drafter_reward_positive` 排除（reward_positive 返回 0 条，silver 不进 gold 集，守卫未放宽）

## 4. Judge-C 候选四元组脚手架构建器

- [x] 4.1 在 `scripts/finetune/export_dataset.py` 增 `judge-c-scaffold` 子命令：按 `contract_type` 把 `type_validations`（含 `law_ref`/`message`/`constraint_id`/`field`）× `clauses` 正文 × `law_info` 法条摘要配对，产出候选四元组；用 char-bigram 相关性 + field==section 精确匹配选 top-3 条款，零重叠规则跳过（208 规则命中 / 50 跳过，避免全笛卡尔积 27215 条）
- [x] 4.2 候选标 `tier:silver`、`provenance: scaffold:machine:type_validations:<id>:clause:<id>:<exact|fuzzy>`、`annotated_by/reviewer: machine_self_eval`、`verdict` 默认 `fail`；`legal_base.source` 标 `law_info:<llm_source>`（deepseek/doubao），law_info 文本截断为 300 字检索提示
- [x] 4.3 候选过 `validate_quadruple` 校验（已扩展接受 silver：silver 须 machine_self_eval + verdict=fail）；**608/608 通过，0 拒绝**
- [x] 4.4 产出落 `data/finetune/judge-c/judge_c_scaffold.jsonl`（silver，608 条）；构建器不直接写 `judge_c_gold.jsonl`（已验证：运行后 gold 文件不存在）

## 5. 脚手架人工核验晋金路径

- [x] 5.1 确认晋升路径：人工核验产出文件经 `export_dataset.py judge-c --gold <file>` 校验后落 `judge_c_gold.jsonl`，构建器自身不写 gold（scaffold 只写 silver 文件）
- [x] 5.2 确认 gold 四元组校验规则就位：`validate_quadruple` 强制 `tier:gold` 须 `reviewer:human`、`verdict=pass` 须 `reviewer:human`、`citation` 非空、机器 pass 降级 fail
- [x] 5.3 验证 `flywheel_gate()`：gold 不存在/为空时返回 False 并拒绝（实测 exit 1）；gold 非空时放行（代码路径：文件存在且 records 非空 → True）

## 6. law_info 机器生成降级约束

- [x] 6.1 验证脚手架候选引用 `law_info` 时 `legal_base.source` 标 `law_info:deepseek`/`law_info:doubao`，且候选 `tier` 仍为 silver（实测首条 source=law_info:deepseek, tier=silver）
- [x] 6.2 验证 law_info 物料不因被脚手架引用而晋升 gold（608 条全部 silver/fail）；人工核验采纳 law_info 表述时须改标权威来源——gold 校验要求 `reviewer:human`，构建器不写 gold，故自动晋金在代码层不可能

## 7. 文档与校验收尾

- [x] 7.1 更新 `docs/finetune-data.md`：表/分层地图扩到 11 张、银牌真实数 131、scaffold 流程、law_info bronze 告示
- [x] 7.2 `openspec validate --change expand-finetune-data-sources` 通过
- [x] 7.3 全套脚本幂等重跑（抽取/去重/脚手架/校验），既有表与运行时零影响（extraction 字节级幂等已验证）
