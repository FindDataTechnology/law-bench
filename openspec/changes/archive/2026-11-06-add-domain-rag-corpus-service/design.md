# 设计：按域 RAG 语料服务

总纲：`docs/knowledge-platform-blueprint.md`（C4，P2）。现状盘点：`src/search/`（minio_source/embeddings/ingest/vector_store/query/rag_tool）+ `src/web/routes/search.py`；配置在 `src/settings.py`（`SEARCH_INDEX_NAME` 缺省 `contracts`、MINIO_* 全局）。

## D1 索引归属解析，最小侵入

**不重写 search 栈，只加一层「域→索引」解析**：

```
resolve_index(conn, domain_key: str | None) -> str
  None  -> SEARCH_INDEX_NAME（settings 常量，legal 权威，逐字兼容路径）
  'legal' -> SEARCH_INDEX_NAME（登记行存在则用登记值，否则缺省——法律域追溯登记）
  其他 -> rag_corpora 登记值；未登记 -> raise CorpusNotRegistered
```

`get_vector_store()`/`do_search()`/`run_ingest()` 全部改收 `index_name` 参数（现签名无参→内部用常量；改为显式传参，调用点全在 search 路由与 CLI，改动面小）。`get_embed_model()` 不动（D4 声明位留好不实现）。

## D2 rag_corpora 表（进 WORKSPACE_SCHEMA，幂等三件套）

```
rag_corpora  id, domain_id FK domains UNIQUE, index_name TEXT NOT NULL UNIQUE,
             sources JSONB NOT NULL DEFAULT '[]'   -- [{bucket, prefix}], 空=继承法律缺省? 不：空=未配置语料源（可检索已摄取内容但不可摄取）
             embedding_model TEXT NULL,            -- 声明位，NULL=全域缺省
             registered_by TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT now()
```

索引名约定：登记时校验 `{domain_key}-` 前缀（防跨域误指同一索引）；`legal` 例外允许 `SEARCH_INDEX_NAME` 值（追溯迁移）。

## D3 摄取域化

`run_ingest(domain_key, prefix=None)`：读 `rag_corpora.sources`，逐 (bucket, prefix) 拉 `load_documents`（minio_source 已支持 prefix 参数与 bucket 传参），`chunk_documents` 后 `vector_store` 写入该域索引。幂等：沿 llama-index ESVectorStore 既有 upsert 语义（同 doc id 覆盖），doc id = `{bucket}/{key}` 路径键（现实现即此）。CLI `python -m src.search.ingest --domain legal --prefix ...`。

**法律域零迁移**：不重摄、不重建索引；`rag_corpora` 给 legal 插一行 `index_name=SEARCH_INDEX_NAME 缺省值`（`ensure_schema` 后的注册脚本或首次访问时追溯登记——选启动时 `ensure_schema` 内 seed，幂等）。

## D4 检索面与 RBAC

- `/api/search?q=&top_k=&domain=`：`domain` 缺参→legal 解析路径（零行为变化）；带参→`resolve_index` + 域成员两道（`require_scope("content:read")` + `require_domain_role("annotator")`）。
- **兼容红线**：现行 `/api/search` 无鉴权豁免吗？查现状——search 路由在 app 级 `get_current_user` 之下（非豁免前缀），即现在就需要登录。缺参路径保持现状（登录后即可检索 legal）；带参路径加域角色检查。页面 `/search` 同构。
- 未登记域：400 + 如实「域未登记语料」，非 404。

## D5 admin 登记面

`/admin/domains/{domain_key}` 域详情页加「RAG 语料」区：索引名（只读展示+登记表单）、sources 编辑（JSON 或逐行 bucket/prefix）、摄取按钮（触发 `run_ingest`，异步 flash 结果）。沿 C1 域详情既有结构（admin.py 加 2 个 POST 路由）。

## D6 风险

- 风险①：`/api/search` 现状鉴权需实查（若 public_app 挂了匿名只读变体则兼容面更大——apply 期实查再定缺参路径是否需要豁免保持）；
- 风险②：ES 索引 dims 由嵌入模型决定，全域同模型（本期约束），跨模型切索引须重建——声明位留好，docstring 写明；
- 风险③：摄取在 web 请求线程内跑大语料会超时——admin 触发改为 fire-and-forget 线程 + 结果落日志（沿 wire scheduler to_thread 先例），CLI 才是批量通道。
