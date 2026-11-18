# 提案：按域 RAG 语料服务通用化（C4，P2）

## Why

总纲（`docs/knowledge-platform-blueprint.md`）裁定「RAG 资产位 P0 天然成立，服务通用化留 P2」。现状 `rag-search` 能力是**单域专用**：ES 索引名全局一个（`SEARCH_INDEX_NAME`，缺省 `contracts`）、语料源固定 MinIO `templates`/`drafts` 两前缀、查询路由无域参数——柏讯数据域语料进来就会和法律语料混在一个索引里，无法按域隔离、无法按域选嵌入配置。多领域平台要求「按域配置语料源/嵌入/检索」。

## What Changes

- **域语料注册（语料模板落地面）**：域工作区的模板三件套中 `corpus_declaration` 升级为一等配置——每域可声明 ES 索引名、MinIO 桶+前缀清单、嵌入模型（缺省沿全域配置）；落 `rag_corpora` 表（域唯一），管理面（admin）可登记。
- **摄取管线域化**：`run_ingest(domain_key)` 按 `rag_corpora` 声明拉语料、分块、写入该域索引；索引名约定 `{domain_key}-{suffix}`（缺省 suffix=rag）；法律域迁移：首次部署自动把旧 `contracts` 索引登记为 legal 域语料（零重摄取，行为零变化）。
- **检索面域化**：`/api/search` 增 `domain` 参数（缺省 legal 兼容旧调用）；未登记域返回空集如实；跨域不可见（域不匹配≠404，空集+如实标记）。
- **查询授权**：检索路由挂域成员检查（沿 `require_domain_role("annotator")` 两道）——RAG 内容是域资产，非成员不可检索。
- 非目标：嵌入模型按域微调/多模型路由（声明位留好，本期全域同一嵌入模型）、摄取调度器（手动 CLI 触发沿用）、发布面含语料（金集/语料发布挂后续）、DQA 数据金集（另立）。

## Capabilities

### New Capabilities

- `rag-corpus-service`: 按域 RAG 语料服务——域语料登记、域化摄取、域化检索、检索授权

### Modified Capabilities

- `rag-search`: 现有七需求的行为保留为 legal 域实例（Document Source/Embedding/Vector Store/Ingestion/Search API/Search Page/Retrieval Tool 的语义不变，归属域化后的 legal 实例）；`/api/search` 增可选 `domain` 参数为增量兼容

## Impact

- **代码**：`src/search/`（vector_store/query/ingest 增域参数与索引解析）、`src/web/routes/search.py`（域参数+RBAC）、`src/bench/workspace_store.py` 扩 `rag_corpora` 表、admin 页加语料登记区。
- **兼容**：`SEARCH_INDEX_NAME` 环境变量保留为 legal 缺省；旧测试全绿（legal 行为零变化）；`/api/search` 不带 domain 参数行为逐字不变。
- **测试**：域索引隔离（两域互不可见）、摄取按声明、未登记域空集、RBAC 三档、法律域回归。
