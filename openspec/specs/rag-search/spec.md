# rag-search Specification

## Purpose
Provide semantic search over ingested legal documents: MinIO document source, OpenRouter embeddings, Elasticsearch vector store, an ingestion pipeline, and a search API/page. Per-domain corpus resolution is layered on top while the legacy legal index stays byte-compatible.

## Requirements

### Requirement: Document Source in MinIO
The system SHALL read contract documents (seed templates and generated drafts) from an S3-compatible MinIO bucket configured via environment (`minio_host`, `minio_root_user`, `minio_root_password`). Documents SHALL be organized under a configured bucket with prefixes separating templates from drafts (e.g. `templates/` and `drafts/`). The system SHALL read documents lazily from MinIO rather than from the local filesystem, so the corpus is shared and durable across processes.

#### Scenario: List and read documents from the bucket
- **WHEN** the ingestion pipeline runs against a configured MinIO bucket containing `templates/service-agreement.md` and `drafts/employee-nda.md`
- **THEN** both documents are read from MinIO as markdown text
- **AND** no document is read from the local `templates/` or `output/` directories

#### Scenario: Bucket and prefix are configurable
- **WHEN** the bucket name or the templates/drafts prefixes are changed via environment
- **THEN** ingestion reads from the newly configured locations without code changes

### Requirement: Embedding via OpenRouter
The system SHALL embed document chunks and queries using the `nvidia/nemotron-3-embed-1b:free` model served through OpenRouter's OpenAI-compatible `/api/v1/embeddings` endpoint, configured via `OPENROUTER_API_BASE` (default `https://openrouter.ai/api/v1`) and `OPENROUTER_API_KEY`. The output embedding dimension SHALL be 2048. Ingestion (document) embeddings and query embeddings SHALL use the same model and dimensions.

#### Scenario: A chunk is embedded to a 2048-dimensional vector
- **WHEN** a document chunk is embedded via the OpenRouter embedding client
- **THEN** the returned vector has exactly 2048 float dimensions
- **AND** the request is sent to `OPENROUTER_API_BASE`/embeddings with model `nvidia/nemotron-3-embed-1b:free`

#### Scenario: Query and document embeddings share the model
- **WHEN** a search query is embedded at query time
- **THEN** it uses the same model and 2048 dimensions used at ingestion time
- **AND** cosine similarity between query and document vectors is meaningful

#### Scenario: Free-tier limits and unavailability are handled
- **WHEN** the OpenRouter `:free` model returns a rate-limit or availability error during ingestion
- **THEN** the client retries with backoff and, on persistent failure, records the failed chunk without aborting the whole ingestion batch
- **AND** a clear error is surfaced for manual retry

### Requirement: Elasticsearch Vector Store
The system SHALL store document chunk embeddings in an Elasticsearch index configured via `elastic_search_host`, `elastic_search_user`, and `elastic_search_pass`. The index mapping SHALL declare a `dense_vector` field with `dims: 2048` and `similarity: cosine` (the model output is L2-normalized, so cosine and dot-product agree). Each indexed document SHALL carry the chunk text and metadata (source document path, contract type where derivable, and section/heading where available). The system SHALL detect a dimension mismatch between the configured model and an existing index and refuse to silently corrupt the index.

#### Scenario: The index is created with the correct mapping
- **WHEN** the vector store is initialized against an Elasticsearch cluster with no prior index
- **THEN** an index is created with a `dense_vector` field of `dims: 2048` and `similarity: cosine`
- **AND** stored documents carry their chunk text and source metadata

#### Scenario: Dimension mismatch is rejected
- **WHEN** the configured embedding model implies 2048 dims but an existing index was created with a different dimension
- **THEN** the system raises a clear configuration error rather than writing mismatched vectors
- **AND** no partial vectors are written

#### Scenario: A model swap requires reindexing
- **WHEN** the embedding model is changed after documents have been indexed
- **THEN** the system requires an explicit reindex (drop and re-ingest) before search
- **AND** search is not served against stale vectors of the wrong dimension

### Requirement: Document Ingestion Pipeline
The system SHALL provide a re-runnable pipeline that reads documents from MinIO, splits each into chunks, embeds the chunks via OpenRouter, and upserts them into the Elasticsearch vector store. The pipeline SHALL be idempotent: re-running it over unchanged documents SHALL NOT create duplicate chunks. The pipeline SHALL be invokable from a CLI entry point and SHALL report progress and any per-chunk failures.

#### Scenario: Run ingestion over the corpus
- **WHEN** the ingestion pipeline is run against a populated MinIO bucket
- **THEN** every document is chunked, embedded, and stored in Elasticsearch with source metadata
- **AND** the run reports the number of documents and chunks ingested

#### Scenario: Re-running ingestion is idempotent
- **WHEN** the ingestion pipeline is run a second time over unchanged documents
- **THEN** no duplicate chunks are created
- **AND** changed documents are updated and deleted documents are removed from the index

#### Scenario: A single bad document does not abort the batch
- **WHEN** one document fails to parse or embed during ingestion
- **THEN** the pipeline records the failure and continues with the remaining documents
- **AND** the run exits non-zero only if no document was ingested successfully

### Requirement: Semantic Search API
The system SHALL expose a JSON endpoint `GET /api/search?q=<query>` (and an equivalent `POST` accepting a query body) that returns ranked chunks for a natural-language query using the LlamaIndex query engine over the Elasticsearch vector store. Each result SHALL include the chunk text, its source document path, and a relevance score. The endpoint SHALL return an empty result list (not an error) when no chunks match.

#### Scenario: Search returns ranked chunks for a Chinese query
- **WHEN** a client requests `GET /api/search?q=保密义务` against an indexed corpus
- **THEN** the response is a JSON list of chunks ranked by cosine similarity
- **AND** each result carries its chunk text, source document path, and score

#### Scenario: No matches returns an empty list
- **WHEN** a client searches for a query with no similar chunks in the index
- **THEN** the response is `[]` with HTTP 200
- **AND** no error is raised

#### Scenario: Search works across locales
- **WHEN** a search query is submitted in Chinese or English
- **THEN** ranked results are returned using the shared embedding space
- **AND** the endpoint does not depend on the UI locale

### Requirement: Search Page
The system SHALL provide an HTML page at `/search` with a query input and a ranked results list, consistent with the existing localized UI chrome (nav, locale switch). Results SHALL link back to their source document where viewable.

#### Scenario: A user searches from the page
- **WHEN** a user submits a query on `/search`
- **THEN** ranked chunks are rendered with their source path and a relevance score
- **AND** the page chrome is localized per the active locale

### Requirement: CrewAI RAG Retrieval Tool
The system SHALL expose semantic retrieval as a CrewAI tool that the drafter agent can call to ground contract generation in retrieved precedent chunks. The tool SHALL be optional and configurable (on/off via environment). When the retrieval backend (MinIO, Elasticsearch, or OpenRouter) is unavailable, the tool SHALL degrade gracefully - returning no context and letting the drafter proceed without retrieval - rather than failing the drafting run.

#### Scenario: The drafter retrieves context before drafting
- **WHEN** the RAG tool is enabled and the drafter agent is invoked
- **THEN** the drafter can call the retrieval tool with the drafting request
- **AND** retrieved chunks are made available as context for generation

#### Scenario: Retrieval is optional
- **WHEN** the RAG tool is disabled via configuration
- **THEN** the drafter proceeds without any retrieval calls
- **AND** drafting behaves as before this change

#### Scenario: Backend unavailability degrades gracefully
- **WHEN** Elasticsearch or OpenRouter is unreachable during a drafting run with the tool enabled
- **THEN** the tool returns no context and the drafter still completes the draft
- **AND** no unhandled exception propagates to the crew

### Requirement: 域归属与兼容缺省

`/api/search` 与检索页 SHALL 支持可选 `domain` 参数：缺省（缺参）SHALL 解析到 legal 域语料（既有 `SEARCH_INDEX_NAME` 环境变量继续作为 legal 索引名的权威来源，行为逐字兼容）；带参数时行为归 `rag-corpus-service` 域化检索契约。

#### Scenario: 缺参逐字兼容
- **WHEN** 既有调用方不带 `domain` 参数请求 `/api/search`
- **THEN** 响应结构与内容来源与升级前一致（legal 索引），零可观测变化

### Requirement: 按域子树过滤的检索

检索 SHALL 接受一个域标识，并把结果限制在该域**经订阅与继承得到的取材范围**内：先解析该域的有效订阅（含父域继承），再按这些订阅的源集合过滤内容块。过滤 SHALL 在检索执行时生效（而非事后裁剪），以保证 top-k 结果全部落在范围内。检索结果 SHALL 保留每块的溯源信息（源、文档、块序号）与所属库标识。

#### Scenario: 子域只看到自己的取材面
- **WHEN** 子域只订阅了库中的「合同样本」源，发起检索
- **THEN** 返回的 top-k 全部来自「合同样本」，不含同库其它源的块，且数量不因过滤而少于请求值（在库有足够内容时）

#### Scenario: 结果可溯源
- **WHEN** 任一检索结果返回
- **THEN** 每条结果都能指出所属库、源、文档路径与块序号

### Requirement: 检索的 fail-closed 与显式空态

未提供域标识的检索 SHALL 仅在平台内部白名单路径（如运维自检）可用，且 SHALL 明确标记为「未限定域」；面向租户的检索调用缺少域标识 SHALL 被拒绝。域无有效订阅时 SHALL 返回显式空态（「该域未订阅语料」）而不是空列表——空列表必须只表示「检索到了但没有匹配」。

#### Scenario: 缺域标识的租户检索被拒
- **WHEN** 租户会话发起检索但未提供域标识
- **THEN** 请求被拒绝并说明必须指定域，不回落全局索引

#### Scenario: 空结果与未订阅可区分
- **WHEN** 一个已订阅域检索无匹配内容
- **THEN** 返回空列表并标注「无匹配」；而未订阅域返回的是「未订阅语料」错误态

### Requirement: 检索范围的可解释性

系统 SHALL 能回答「某域此刻为什么能看到这些内容」：给出该域的有效来源清单（来自哪个库、哪些源、经哪一级继承获得、被哪次收窄规则削减）。该解释 SHALL 与检索实际使用的范围同源计算，SHALL NOT 由页面另行推导。

#### Scenario: 解释继承来的范围
- **WHEN** 管理员查看子域的检索范围说明
- **THEN** 能看到每个源是「本域订阅」还是「继承自父域」，以及被收窄掉的源为何被收窄

### Requirement: 机器取数接口（域化库检索）

系统 SHALL 提供域化的库检索接口（`GET /api/library/search`），以调用方的**有效订阅**（含继承与收窄）为范围，并按各库自己的嵌入模型生成查询向量。响应 SHALL 用状态码区分三种结果：命中/无命中为 200（`hits` 可空）、该域无任何订阅为 400、上游向量库或嵌入器失败为 502。未知域 SHALL 返回 404。该接口 SHALL 与页面检索共用同一范围解析器与同一域访问闸，SHALL NOT 提供绕过域授权的路径。

#### Scenario: 命中与无命中都是 200
- **WHEN** 已订阅域的一次检索没有相近内容
- **THEN** 返回 200 且 `hits` 为空数组，调用方可据此判「没有匹配」而非「出错」

#### Scenario: 未订阅与上游故障可区分
- **WHEN** 请求的域没有订阅任何库
- **THEN** 返回 400 并说明该域未订阅语料；若改为向量库不可达，则返回 502 并带上失败原因，两者都不返回空结果

#### Scenario: 不能绕过域授权
- **WHEN** 非该域成员用查询参数指定该域调用此接口
- **THEN** 请求在域闸处被拒（401/403），不返回该域任何内容
