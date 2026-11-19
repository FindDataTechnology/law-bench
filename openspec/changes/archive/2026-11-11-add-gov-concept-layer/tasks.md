## 1. 取样器：块表 join 文档表取标题

- [x] 1.1 `_sample_text_tables` 读 `ingest_rule.document`：有 `table`+`doc_ref`+`title` 且三个标识符安全时 LEFT JOIN 取标题；验证＝单测：桩表 `id/document_id/chunk_text` + 文档表 → 每块带标题（`test_the_title_comes_from_the_declared_document_table`）
- [x] 1.2 无文档表声明、或无标题列时 `title` 为 `None` 且不抛错；验证＝`test_a_chunk_table_without_any_title_column_still_samples`
- [x] 1.3 `text`/`id` 列缺失仍报错并点名；验证＝`test_a_missing_text_column_is_an_error_naming_it` / `test_a_missing_id_column_is_an_error_naming_it`
- [x] 1.4 登记脚本声明政务块侧列映射；验证＝重跑 `register_libraries.py --only text` 输出 `source gov exists; chunk columns merged (id->id, text->chunk_text)`，且随后取样取到 6 块

## 2. 模板 v2：概念与依据关系

- [x] 2.1 `gov-domain` 发 v2：`entity_types` 增 `concept`，`relationship_kinds` 增 `defines`；验证＝发布输出 `published template 'gov-domain' v2 (id=4)`，v1 行未改
- [x] 2.2 政务域切到 v2，回滚点＝`domains.template_id=3, template_version=1`；验证＝发布输出 `re-anchored domain 'gov': v1 -> v2`
- [x] 2.3 v2 下 `concept` 候选被词表闸放行；验证＝`skipped.bad_kind = 0` 且 `by_kind.concept = 2`

## 3. 包声明 concept 岗位

- [x] 3.1 `packs/gov/pack.yaml` 增 `concept`：`sources: [gov]`、`batch_chunks`、`min_usable_rate`、`max_total`；验证＝`agent_team.plan('gov')` 中 concept 可运行且参数为 `{'batch_chunks': 10, 'min_usable_rate': 0.5, 'max_total': 40, 'sources': ['gov']}`

## 4. 真跑一轮并如实过审

- [x] 4.1 注入 `FDTEXT_DATABASE_URL` 后 `sample_chunks(domain_path='gov')` 取到块；验证＝返回 6 块，标题来自文档表
- [x] 4.2 跑一轮概念抽取（限量），报告各计数；验证＝`批 concept-gov-3：采样 6 块，产出 3 条，入箱 2 条，可用率 0.667；类型分布：concept×2`
- [x] 4.3 逐条过审：引文逐字命中才接受，`key_already_live` 的驳回；验证＝`pending` 归零，接受 5 条、驳回 2 条（`财政部` key_already_live；`3年期固定利率附息债` 个案描述非概念）
- [x] 4.4 接地：接受的概念挂 `defines` 到其依据公文；验证＝`quality.grounding(namespace='gov')` = `value 1.0, 3/3`，`gaps` 为空

## 5. 途中修掉的真问题（顺带账）

- [x] 5.1 `complete()` 把「预算截断」静默返回空串，导致整轮报「语料可能不含可抽内容」；改为抛 `ExtractionError` 点名截断与推理 token 数；验证＝`test_a_length_truncated_answer_raises_instead_of_returning_empty`
- [x] 5.2 默认 `EXTRACT_MAX_TOKENS` 1500 实测必截断（两块的提示词花 3,531 推理 token），默认改 4000 并同步清单；验证＝`test_the_default_budget_is_one_a_real_call_fits_in` + 4000 档真实调用 `finish=stop`
