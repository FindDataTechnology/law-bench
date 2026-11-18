# Proposal: link-law-catalog-audit

## Why

合同侧的法律引用全部是裸字符串：条款的 `law_refs` 由 `《...》` 正则从条款体派生（`src/clauses/store.py`），与真实法规的存在性、时效状态完全脱节——条款库抽取自真实模板，其中引用已废止法律（如 2021 年废止的《合同法》）、被新司法解释取代的旧版本的情形无法被系统发现。外部法规库已建成（PG `law_db.laws`，21,746 部，含 status/publish/category 元数据，Qdrant payload 的 law_id 与其一致），现在以只读目录副本 + 纯 SQL join 的方式建立关联，成本最低、且引法审计立刻有回报。

## What Changes

- law-bench 主 PG 新增 `law_catalog` schema：`laws` 只读副本表（法规库 PG 一次性导出 → RustFS → 导入脚本），支持按需重灌（flk 新法速递增量后手动刷新）。
- 新增名称解析器：归一化（去"中华人民共和国"前缀，沿用 `legal_refs._dedup_key` 规则）→ 人工别名表（简称/旧称 → 全称）→ pg_trgm 模糊匹配过阈值 → 未命中进人工复核队列。
- 新增 `clause_law_refs` 解析结果表（clause_id × law_id × status × resolved_via），由独立的可重跑解析任务写入；**不改动** `law_refs` 派生列及其从 body 重算的管线。
- 新增全库引法审计：按法规 `status` 分级（`已废止`/`失效` = 引用已废法律；`已修改` = 单列疑似；NULL/脏值 = 兜底清单），输出 markdown 报告 + web 复核队列入口。
- 明确禁止事项写入设计与规格：`expiry` 列语义是施行日期，任何判定逻辑不得使用；`law_id`/`chunk_no` 以字符串处理，不做数字强转。

不改动：条款 `law_refs` 派生管线、ES 向量检索、Qdrant/embedding（本变更零向量依赖、零对 law-rag 服务的运行时耦合）。

## Capabilities

### New Capabilities

- `law-catalog`: 法规目录只读副本（导入、刷新、约束）与法律名称解析（归一化、别名表、模糊匹配、复核队列），以及条款引用到 law_id 的解析结果表。
- `law-citation-audit`: 基于目录副本的条款库全量引法审计——状态分级判定、报告产出、人工复核流程。

### Modified Capabilities

（无——现有 `rag-search`、`industry-standard-reference`、`law-info-web` 的规格行为不变。）

## Impact

- **代码**：新增 `src/law_catalog/`（导入 + 解析 + 审计）或等效模块；`clauses/audit.py` 挂审计入口；web 新增审计报告/复核路由与页面；MCP 可选暴露审计工具。
- **数据库**：主 PG 新增 `law_catalog` schema（laws 副本表、别名表、clause_law_refs 表），随现有备份体系走。
- **外部依赖**：无新增运行时依赖（纯 SQL join）。一次性人工动作：法规库侧 `SELECT id,title,category,publish,expiry,status,src_db,content_status FROM laws` 导出并上传 RustFS。
- **数据风险**：目录副本是只读镜像，重灌幂等；解析层可重跑，审计为报告型产出，均不修改条款本体。
