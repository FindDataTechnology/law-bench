# 任务：add-domain-rag-corpus-service

## 1. 数据层与解析层

- [x] 1.1 `rag_corpora` 表进 `WORKSPACE_SCHEMA`（domain_id UNIQUE、index_name UNIQUE、sources JSONB、embedding_model NULL）+ `conftest._ALL_TABLES`；`ensure_schema` 幂等 seed legal 行（index_name=SEARCH_INDEX_NAME，调用期取值 honoring monkeypatch，legal 域不存在时零操作）
- [x] 1.2 `src/search/resolver.py`：`resolve_index`（None/legal 缺省路径逐字兼容、未登记 CorpusNotRegistered 报名）+ `register_corpus`（upsert per-domain、`{domain_key}-` 前缀校验 legal 豁免、sources 形状六连验）+ `get_corpus/list_corpora`
- [x] 1.3 `vector_store.get_vector_store(index_name=None)`、`query.search(..., index_name=None)`、`ingest.run_ingest(domain_key, prefix, conn)` 域化签名（minio_source.load_documents 增 bucket 参数）；CLI `--domain` 缺省 legal；rag_tool 零改动走 legal 缺省

## 2. 路由与 RBAC

- [x] 2.1 `/api/search` 增 `domain` 可选参数：缺参 legal 零变化（无 DB 触碰）；带参两道序贯（Request scope 重注 domain_key 复用 require_domain_role 工厂）；未登记 400 如实；API-key 通道钉死 legal 缺省（docstring 记决策）；`/search` 页面同构
- [x] 2.2 admin 域详情页「RAG 语料」区（当前语料/登记表单/摄取按钮 daemon 线程 fire-and-forget），admin.py 加 register/ingest 两 POST 路由（admin+lead 两道）
- [x] 2.3 i18n 双语（`admin.rag.*` 全节 + `search.domain_*` + 5 个 flash 键）

## 3. 测试

- [x] 3.1 解析层 18 测试：None/legal 兼容、登记解析、未登记拒绝、前缀校验（跨域误指仅经 legal 豁免路径可达=分层防御）、六种 sources 形状、upsert-replace
- [x] 3.2 隔离与幂等：摄取按源逐个调用、写落登记索引、legal 无行走 legacy 形状、空 sources 诚实零操作
- [x] 3.3 RBAC 15 测试：带参非成员 fail-closed、门序（scope 先）、API-key 钉死 legal、admin/lead 合成、摄取线程确定性验证（threading.Event）
- [x] 3.4 法律域回归：全量 1311 绿（search/rag 既有测试零改动通过）

## 4. 收口

- [x] 4.1 全量回归 + `openspec validate add-domain-rag-corpus-service --strict` 绿
- [x] 4.2 blueprint 台账更新（C4 状态）与 tasks.md 对账
