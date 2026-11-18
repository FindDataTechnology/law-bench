## Why

上一版把本体「能填」做出来了，但**填什么**还是空白：法律域 364,916 块语料在手，本体里只有 11 条单元（其中 5 条是冒烟数据）。靠人手把实体与关系从 36 万块里读出来，是几十人月的事——这正是「快速填充细分领域 ontology」现在卡住的地方。

已经有两条基础设施可以直接接上：`law-library` 的语料已可按域订阅并检索（Qdrant 带 `law_id/title/category/law_type`），`domain_proposals` 提案层已具备「提交-证据-digest-幂等-人工确认」的完整链路。缺的是中间那一步：**从语料里读出候选，并以提案形式排进人的复核队列**。

## What Changes

- 新增「候选抽取」作业：按域 + 库源范围取样若干语料块，让模型按该域模板声明的 `entity_types` / `relationship_kinds` 产出候选实体与候选关系；每条候选都必须带**逐字引用**（chunk 标识 + 原文片段）。
- 候选**不直接写本体**：全部落成 `domain_proposals`（pending），由人在收件箱确认；确认仍走内核，事件照旧。
- 新增**逐字校验闸**：候选引用的原文片段必须真实出现在被引块里，否则该候选在入库前就被丢弃并计数（防模型编造证据）。
- 抽取作业可指定批量标识（batch），复核页可按批次筛选与批量确认/驳回。
- 作业有硬上限：每次最多取 N 块、每块最多 M 条候选、单次运行的总候选上限，超限即停并有明确报告。

## Capabilities

### New Capabilities

- `ontology-extraction`: 从既有语料产出本体候选的契约——候选必须携带可校验的逐字证据、必须落在提案层而不是本体、必须受模板词表约束、必须可幂等重跑，且有明确的量级与成本上限。

### Modified Capabilities

（无。提案层与内核的行为不变：本变更只是多了一个「提交者」，提交者仍是普通提交方。）

## Impact

- 代码：新增 `src/bench/extraction.py`（取样 → 调模型 → 逐字校验 → 提交提案）；`src/bench/proposals.py` 可能要给 evidence 增加 `batch` 与 `quote` 的约定（schema 不变，走 JSONB）；收件箱增加按批次筛选与批量操作。
- 依赖：模型调用经现有网关（与 judge 同一套凭据），需要 `OPENROUTER_API_KEY` 或词元网关；抽取作业在应用内以后台任务/CLI 运行，不进请求路径。
- 数据：只写 `domain_proposals`（pending）。**不写** `knowledge_units`，除非人确认。
- 风险：模型幻觉（靠逐字校验闸拦）、成本失控（靠硬上限）、重复候选（靠 `(domain, source, external_key)` 幂等 + evidence digest）、把测试数据当语料（沿用 `is_smoke` 标注）。
