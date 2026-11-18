## 1. 目录结构与溯源清单格式

- [x] 1.1 建 `data/finetune/` 目录树：`data/finetune/judge-c/`（四元组）、`data/finetune/drafter-a/`（配对）、`data/finetune/warehouse/`（仓内抽取物料）、`data/finetune/opensource/`（开源接入物料）、`data/finetune/manifests/`（溯源清单）
- [x] 1.2 定溯源清单 JSONL schema：每条含 `dataset`、`source`（warehouse|opensource|human）、`license`、`tier`（gold|silver|bronze|raw）、`provenance`、`row_ref`，附一份 `data/finetune/manifests/manifest.schema.json`
- [x] 1.3 写 `docs/finetune-data.md` 顶层说明：分层定义、bronze「永不作 ground truth」醒目告示、飞轮顺序约束、覆盖缺口指针

## 2. 仓库只读抽取脚本

- [x] 2.1 写 `scripts/finetune/extract_warehouse.py`：在 pod 内经 `psycopg.connect(os.environ['database_url'])` 执行纯 SELECT，导出 `clauses`/`pipeline_runs`/`eval_runs`/`eval_criteria_results`/`rubrics`/`criteria` 全量物料到 `data/finetune/warehouse/`，零写
- [x] 2.2 每条物料带 `provenance`（`<table>:<id>`）、`source: warehouse`、`tier`（clauses→raw、filled_text→silver、eval_criteria_results→bronze、rubrics/criteria→gold）
- [x] 2.3 验证幂等：同库连跑两次，物料清单逐字节相同、条数相同；验证 SQL 全为 SELECT（grep 无 INSERT/UPDATE/DELETE 指向既有表）
- [x] 2.4 在抽取产出末尾刷新覆盖缺口清单 `data/finetune/manifests/coverage_gaps.jsonl`：零-pipeline 类型（`zero_pipeline_runs`）与 custom 偏薄（`custom_thin`，阈值 500，当前 267），刷新不产生重复条目

## 3. bronze 守卫与分层过滤

- [x] 3.1 在导出器（`scripts/finetune/export_dataset.py` 或等价单点）实现 bronze 守卫：任何下游按 ground-truth 用途取 `tier: bronze` 物料时报错拒绝
- [x] 3.2 实现按层过滤的加载器：支持「gold 及以上」「silver 及以上」等过滤语义，过滤逻辑单点
- [x] 3.3 验证：bronze 物料无法进入任何标注 gold/silver 的输出集；加载器「gold 及以上」只返 gold

## 4. 开源语料许可证闸门

- [x] 4.1 写 `scripts/finetune/ingest_opensource.py`：读候选语料包的 `LICENSE` 文件做字符串匹配，`license_allowlist = {Apache-2.0, MIT}`，不在白名单整包拒绝
- [x] 4.2 拒绝事件落 `data/finetune/manifests/rejected_sources.jsonl`（语料名 + 许可证 + 拒绝原因）；缺许可证的包按「缺少许可证声明」拒绝
- [x] 4.3 接入 DISC-Law-SFT（Apache-2.0，法律推理 SFT 暖启）入池，标 `source: DISC-Law-SFT`、`license: Apache-2.0`、`tier: silver`
- [x] 4.4 接入 CAIL2018（MIT，裁判推理）入池；接入 SAMR 模板（起草结构骨架）
- [x] 4.5 确认 ChatLaw（AGPL-3.0）/LaWGPT（GPL-3.0+严禁商业）在拒绝清单中、池中无其物料

## 5. Judge-C 四元组数据集

- [x] 5.1 定四元组 JSON Schema `data/finetune/judge-c/quadruple.schema.json`：`legal_base{source,text}`、`clause_text{body,section}`、`verdict∈{pass,fail}`、`reasoning{justification,citation[]}`，`citation` 非空
- [x] 5.2 在导出器实现标注规则校验：`verdict=pass` 仅在 `provenance.reviewer=human` 时允许；机器自评即便判 pass 强制降级 fail 或丢弃；机器来源标 `machine_self_eval`
- [x] 5.3 校验器跑通：缺法律依据的四元组被拒、机器 pass 被降级、人工 pass 含 ≥1 citation 且标 `human_annotated`/`tier:gold`
- [x] 5.4 留出 Phase-1 标注种子入口（top-5 类型 sale/employment/property_service/technology/film_production ×100 ≈ 500 四元组）——schema 与校验就绪即可，人工标注属后续运营不在本任务

## 6. Drafter-A 配对数据集

- [x] 6.1 定配对 JSON Schema `data/finetune/drafter-a/pair.schema.json`：`task_desc`、`slots[]`、`body`（已填正文）
- [x] 6.2 从 `pipeline_runs` 抽银牌配对：`task_desc`+`fill_values` 作输入、`filled_text` 作正文，标 `tier:silver`/`source:warehouse`，共 548 条暖启池
- [x] 6.3 槽位一致性校验：配对正文中 `{{slot}}` 全部已替换为具体值，且替换值键集合 ⊆ 声明 slots
- [x] 6.4 银牌仅 SFT 暖启约束：银牌配对不得进入 reward modeling 正样本集（守卫同 §3 单点实现）

## 7. 飞轮顺序闸门

- [x] 7.1 在 Drafter-A reward/DPO 启动入口实现存在性闸门：检查 Judge-C gold 四元组数据集文件存在且非空，否则报错「Judge-C 数据集未就绪」并拒绝运行
- [x] 7.2 验证：Judge-C 空时 reward modeling 被阻断且不使用 silver 草稿当正样本；Judge-C 就绪后释放

## 8. 校验与收尾

- [x] 8.1 `openspec validate --change add-finetune-data-flywheel` 通过
- [x] 8.2 全套脚本可幂等重跑（抽取/接入/校验），既有表与运行时零影响
- [x] 8.3 更新 `docs/finetune-data.md` 指向最终目录结构、schema、缺口清单
