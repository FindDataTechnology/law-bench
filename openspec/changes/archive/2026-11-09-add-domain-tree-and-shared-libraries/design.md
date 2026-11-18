# Design — 域树 + 行业大库 + 四支柱域化

## Context

现状（全部实测，2026-11-08）：

- `domains` 扁平（`id, key, name, template_id, template_version, created_by, created_at`），只有 1 行 `legal`；无父域、无路径。
- `knowledge_units(kind, namespace, external_key, …)` 的唯一键已包含 `namespace`，但生产数据全是 `'default'`——**分区轴预留了但没用**。
- `rag_corpora` 是「一域一索引」：legal 那行指向 `index_name='contracts'`、`sources=[]`、`embedding_model=null`。
- 检索链路是 LlamaIndex + Elasticsearch：`search(query, top_k, index_name)` **没有任何 metadata 过滤能力**；`_check_dims` 锁 2048 维。
- **生产上 ES 根本没配**：`/search` 页面实测返回「搜索后端不可用 `elastic_search_host is not set`」。也就是说向量库这根支柱目前是「有代码、有注册表、无实例」。
- `rubrics(id, name, context, source, source_path, description, created_at)` 无 `domain_id`；`eval_runs` 按 `rubric_name` 关联。
- `domain_assets(domain_id, asset_kind, asset_key)` 已建表但**零行**。
- 站点是两套 IA 并存：旧顶栏（评分规则/提示词/对比/法律法规/法规索引/合同模板/合同样本/条款库/仪表盘/人工审查/搜索）+ 新域工作台（本体模板/领域工作区）。
- 域工作区固定 6 区：`overview, ontology, bench, inbox, publish, settings`（`src/web/domain_context.py:AREAS`）。

## Goals / Non-Goals

**Goals:**

1. 域可树状组织，**继承只作用于「可见范围与词表」**，不作用于角色与写权。
2. 语料物理单位从「域」上移为「库」：**一份向量，整棵子树共享**；域只持有订阅与收窄。
3. 四支柱都在域上有界面：本体 / 知识库 / 评测标准 / 评测运行，且缺口可见。
4. 新增一个细分域 ≤ 5 分钟（向导），且创建后缺口清单如实可执行。
5. `legal` 域零回归：旧路径全部 302，行为等价。

**Non-Goals:**

- 跨库联合检索、跨库 rerank（一次检索只作用于一个库）。
- 本体自动抽取（仍走舰队提案 → 提案箱 → 专家确认）。
- 多租户向量物理隔离（隔离靠检索过滤 + fail-closed，不靠每域一份索引）。
- 父域角色下行继承（明确禁止，见 Decisions D2）。

## Decisions

### D1 — 域树用材料化路径，不用邻接表递归

`domains` 增 `parent_id BIGINT NULL REFERENCES domains(id)` 与 `path TEXT NOT NULL`（如 `legal`、`legal/contract-review`）。
唯一约束 `UNIQUE(path)`；`path` 由父 `path` + `/` + `key` 在插入时计算，`key` 不可变故路径稳定。

- **为什么**：子树查询是所有热路径（检索过滤、继承、运营台缩进）。材料化路径让「子树」变成 `path = 'legal' OR path LIKE 'legal/%'` 一次索引扫描；邻接表递归（CTE）在每个请求上都要跑一遍树。
- **备选**：Postgres `ltree`（更强，但引入扩展与类型映射，收益在这个深度（≤4 层）不明显）；闭包表（写放大，域数量级只有几十到几百，不值）。

### D2 — 继承只给「读」，不给「权」

- 词表继承：子域模板 `extends` 父模板具体版本，只增不删（spec: ontology-template）。
- 内容可见：父域成员可**读**子树（运营/治理需要）；子域成员**看不到**父域与兄弟。
- 角色：**不继承**。子域负责人必须显式授予。
- **为什么**：继承写权会让「谁能改」变得不可回答；审计与越权演练都要求"角色在域自身定义"。

### D3 — 向量后端换 pgvector，而不是把 ES 装起来

生产 ES 未配置；这一版要做「共享索引 + 过滤检索」，用 Postgres 最省事。

- 表：`corpus_chunks(id, library_id, scope_path, source_key, doc_path, chunk_seq, content, embedding vector(2048), meta JSONB, content_hash)`，索引 `ivfflat/hnsw` + `(library_id, scope_path)` btree。
- 检索：`WHERE library_id = $1 AND (scope_path = $2 OR scope_path LIKE $2 || '/%')` + `ORDER BY embedding <=> $3 LIMIT k`。过滤在 SQL 里、在排序前，天然满足「top-k 全在范围内」。
- **为什么**：与 `knowledge_units`/`rubrics`/`domains` 同库 → 一次事务内的组合查询；已有 `fd-postgres` pg16 运维配方；少一个集群等于少一个故障面。
- **备选**：ES 8 filtered kNN（能力够，但要新集群 + 索引 mapping 维护 + 当前代码路径要重写同样的过滤）；Qdrant（又一个独立服务）。
- **代价（诚实记下）**：`pgvector` 的 HNSW 在千万级向量时的召回与内存不如 ES；本版按「每库 ≤ 百万块」设计，超限再评估分片。

### D4 — 语料模型：库 / 源 / 订阅 三层

```
libraries(id, key UNIQUE, name, backend, embedding_model, dims, created_by)
library_sources(id, library_id, source_key, uri, content_type, ingest_rule JSONB)
domain_library_subscriptions(domain_id, library_id, source_filter JSONB, created_by)   -- UNIQUE(domain_id, library_id)
```

- 有效取材范围 = 沿 `path` 向上收集所有订阅，父域在前、子域收窄在后；收窄只能**减**不能加。
- `rag_corpora` 保留为**兼容投影**（由订阅推导），不再作为写入面；读它的旧代码路径继续工作。
- **为什么**：`library_sources.ingest_rule` 把「切分/去重/最小长度」变成数据而不是代码，新增领域不需要发版。

### D5 — 本体按 namespace 域化，不新增列

`knowledge_units.namespace` 从 `'default'` 改为域 `path`（`legal`、`legal/contract-review`）。读取沿路径向上：先查本域，再父域，同 `(kind, external_key)` 本域优先。
新增 `derived_from JSONB`（溯源：来自哪个库的哪个块/哪条 KU）与复用现有 `tier`（raw→bronze→silver→gold）记录特化进度。

- **为什么**：唯一键已经是 `(kind, namespace, external_key)`，改语义零 DDL 风险；`namespace` 原本就是为此预留（代码注释「namespace」而非「domain_id」）。
- **迁移**：现有 11 行 `namespace='default'` → `'legal'`。

### D6 — rubric 域化 + 引用式继承（不做物化）

`rubrics` 增 `domain_id BIGINT NOT NULL REFERENCES domains(id)`、`derived_from BIGINT NULL REFERENCES rubrics(id)`、`fork_diff JSONB`。

- 解析顺序：本域同名 → 沿父链向上。同域内不允许同名（`UNIQUE(domain_id, name)`）。
- fork 必须写 `fork_diff`（哪几条判据变了），否则 API 拒绝。
- **为什么**：与「取材用引用」保持一致——同一条口径只有一处定义，改父域就是全子树生效；fork 是显式的例外，且留痕。

### D7 — IA 三层 + 域内 8 区

```
L0 /d                    全域运营台（缺口矩阵 + 批量派单 + 新建细分域）
L1 /d/{key}              域工作区
    总览 · 本体 · 知识库 · 评测标准 · 评测运行 · 提案箱 · 发布 · 设置
L2 /d/{key}/{area}/{id}  资产详情
```

- `AREAS` 元组扩为 8 项；`min_role` 沿用（`settings` 仍 lead）。
- `bench` 区收窄为「评测运行」（历史正在跑的运行 + 结果）；rubric 管理移到新「评测标准」区；「知识库」区展示有效取材范围（含继承来源）+ 订阅管理 + 库健康。
- 旧路由统一 302 到等价新位置（映射表落在 `domain-estate-console` 的迁移清单里），顶栏只留三层。
- **为什么**：现在的痛点是「进一个域翻六个分册」，多域之后必须有 L0；而 KB/评测标准没有落点，导致用户看不到这两根支柱。

### D8 — 提案箱复用为「取材落点」

舰队（外部）产生的候选 KU 仍走 `POST /api/d/{domain}/proposals` → 提案箱 → 专家确认 → `authoring` 写入 `knowledge_units`。本版只改两处：确认时按域写 `namespace`，以及接受 `derived_from` 溯源字段。
**为什么**：P2 刚上产并验过（`created` 幂等语义、两条鉴权门），新开审批通道会造成第二套真相。

## Risks / Trade-offs

- **[向量迁移丢召回]** 从 ES（未配，无存量）切到 pgvector 不存在数据迁移；但 embedding 模型一旦更换需整库重建 → 库级 `dims`/`embedding_model` 固化，换模型必须显式新建库并双写验证。
- **[子树可见性的性能]** 父域成员读子树需要 `path LIKE` 扫描 → 在 `(library_id, scope_path)` 与 `domains.path` 上建索引；域数量级小，风险可控。
- **[继承导致「改了父域全变」]** 引用式继承会让父域 rubric/源变更立刻影响所有子域 → 变更前在 L0 显示「将被影响的子域数」，并要求确认；这是有意的强一致。
- **[旧路径 302 遗漏]** 旧菜单有 11 个入口，漏一个就是 404 → 用一张显式映射表 + 一条覆盖测试（遍历表里每条都断言 302 目标可用），不靠人工点。
- **[pgvector 走 SQL 过滤会退化]** 若某库的源极不均衡（99% 内容在一个源），按源过滤的 top-k 可能扫很多行 → 先按库 + 子树过滤，源级过滤作为可选的二级收窄；必要时对热门源单独物化视图。
- **[ruff/mypy 与既有约定]** 新增模块要落在 `src/bench`（存储）与 `src/web`（路由）既有 layering guard 下 → 复用 `ensure_schema` 单一 DDL 入口，避免再出现「DDL 没跑到生产」那类事故。

## Migration Plan

1. **DDL（增量、幂等）**：`domains.parent_id/path`、`libraries`、`library_sources`、`domain_library_subscriptions`、`corpus_chunks`、`knowledge_units.derived_from`、`rubrics.domain_id/derived_from/fork_diff`。全部进 `ensure_schema`，由 boot 步骤落地（`boot: schema ensured on database …`）。
2. **数据回填**：`domains` 现有 legal → `path='legal'`；`knowledge_units.namespace='default'` → `'legal'`；`rubrics` 现有 2 行 → `domain_id=legal`；`rag_corpora` 的 legal 行 → 生成 `law-library` + 一条「全源订阅」。
3. **代码切换（按可回滚顺序）**：① 存储与解析（读老路径也走新函数）→ ② 检索切 pgvector（ES 路径保留一段 fallback，仅日志告警）→ ③ 域内 8 区与 L0 → ④ 旧路由 302 → ⑤ 建域向导。
4. **回滚**：前两步是纯新增，回滚=关开关（检索走 ES 分支）；3-5 步是 Web，回滚=还原模板与路由；DDL 不回滚（只增列/新表）。
5. **验证**：`legal` 全页 200、旧 11 条路径逐条 302、未订阅域检索 fail-closed、子树继承的取材范围与解释一致、`openspec validate --strict`。

## Open Questions

- 库的「源」在对象存储里的组织是否统一为 `s3://<bucket>/<prefix>`（还是允许数据集 ID 这类异构源）——影响 `library_sources.uri` 的解析器，但不影响本版行为契约（先按统一 URI + `source_kind` 字段留扩展位）。
- 评测标准的「评测集」（样本集）是否与 rubric 同区管理，还是独立资产类型——本版按 `domain_assets(asset_kind='eval_set')` 先挂架，不建独立页。
