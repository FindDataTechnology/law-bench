## Why

知验台现在只有**一个真实领域（法律）**，域是平的、四根支柱只有本体有界面、向量库在生产上根本没配（`elastic_search_host is not set`）。而产品要快速填充**大量细分领域**（法律→合同审查/合规/诉讼，银行→信贷/零售银行，以及酒店、跨境电商、农业、花卉…），每个域都要有本体、知识库、向量库与评测标准。

按现状每加一个细分域，都要复制一份语料、一份词表、一套 rubric，并新开 6 个页面——填得越多越难维护，且没有任何一页能回答「哪些域还没配语料/还没 rubric」。这一版是核心模块的地基：**把「行业大库」与「细分域树」分层**，让子域从大库取材再特化，把四根支柱做成可继承的一等公民，后续填内容才是加法而不是复制。

## What Changes

- **域树**：`domains` 增加 `parent_id` 与材料化路径 `path`（如 `legal/contract-review`）；新增子域可继承父域模板词表并**只增不删**。继承解析在服务端一次算清，页面不做二次推导。
- **共享库（Library）**：新增 `libraries`（行业大库：一个检索后端 + 一组源 + 一套摄取口径）与 `domain_library_subscriptions`（域订阅哪些源、用什么口径）。**BREAKING**：`rag_corpora` 的「一域一索引」模型被「一库多域订阅」取代，旧行迁移为「legal 域订阅 law-library 全部源」。
- **向量后端换 pgvector**：ES 在生产未配置，改由 `fd-postgres`（pg16 + 既有运维配方）承载；chunk 带 `scope_path` 元数据，检索按「域路径前缀」过滤，**同一份向量被整棵子树共享**，不复制。
- **本体域化**：`knowledge_units.namespace` 从默认值改为域路径（分区轴已存在，无需改表）；读取沿路径向上继承，同 `(kind, external_key)` 子域覆盖父域。KU 增 `derived_from` 溯源，tier 阶梯（raw→bronze→silver→gold）记录特化进度。
- **评测标准域化**：`rubrics` 增 `domain_id` 与 `derived_from`；父域 rubric 默认对子域生效，子域 fork SHALL 记录与父域的差异摘要。`domain_assets` 从空表变成真正的域资产架（本体条目、源、rubric、评测集）。
- **交互重做**：新增 L0 全域运营台（`/d` 缺口矩阵：本体/语料/评测/最近提案/状态 + 批量动作）；域内区从 6 个扩为 8 个（`总览 · 本体 · 知识库 · 评测标准 · 评测运行 · 提案箱 · 发布 · 设置`）；旧顶栏（法律法规/合同模板/条款库/评分规则/搜索…）全部 302 到新位置，站点只剩一套 IA。
- **建域向导与取材流水线**：向导 = 选父域 → 预览继承的模板词表 → 勾选订阅的库源 → 生成缺口清单；取材 = 库源摄取（打 scope）→ 抽取候选 KU（raw）→ 进该域提案箱 → 专家确认 → 升级 tier/加特化注记。**提案箱复用既有 P2 契约**，不新建审批通道。

## Capabilities

### New Capabilities

- `shared-corpus-library`: 行业大库的生命周期——库的登记（后端/索引/嵌入模型/源清单）、摄取口径、域订阅与取材范围、库级健康与覆盖统计；一库多域、子域只订阅不复制。
- `domain-estate-console`: 全域运营台——所有可视域的一览与缺口矩阵（缺本体/缺语料/缺评测）、按缺口批量派单、新建细分域向导、旧路径到新位置的迁移映射。

### Modified Capabilities

- `domain-workspace`: 域从平铺改为树，新增父域/子域关系与继承规则；一域一租户隔离语义不变，但「跨域不可见」扩展为「子树内可见、子树外拒绝」；角色仍为四级。
- `rag-corpus-service`: 语料单位从「域」上移为「库」，域通过订阅获得检索范围；后端由 Elasticsearch 改为 pgvector；索引命名约束改为库命名约束。
- `rag-search`: 检索 SHALL 支持按域路径前缀过滤（子树共享一份向量），未订阅该库的域查不到其内容（fail-closed 语义保留）。
- `ontology-template`: 模板 SHALL 支持 `extends` 继承父域词表（实体类型/关系种类/档位/敏感级），子域只能增补不能删除；模板校验需覆盖继承后的有效词表。
- `evaluation-rules`: rubric 与评测集 SHALL 归属到域并可继承；父域 rubric 默认对子域生效，子域 fork 必须留差异摘要；评测运行结果按域归属统计。

## Impact

- **数据库**：`domains`（+parent_id/+path）、新表 `libraries`/`library_sources`/`domain_library_subscriptions`、`rag_corpora` 迁移、`knowledge_units`（+derived_from，namespace 语义变更）、`rubrics`（+domain_id/+derived_from）、`domain_assets` 启用。全部走 `ensure_schema` 增量 DDL，可在生产库直接落地。
- **检索栈**：`src/search/{vector_store,query,ingest,resolver}.py` 由 LlamaIndex ES 改为 pgvector；`EMBEDDING_DIMS` 保持 2048；新增按 `scope_path` 的过滤与子树检索。
- **Web**：`src/web/domain_context.py`（8 区 + 继承能力）、`domain_console_*` 模板、新增 L0 运营台与建域向导、旧路由 302 映射；`web-rbac` 的角色来源不变。
- **评测**：`evaluation-rules` 的 rubric 读取路径全部带上域参数；bench 区收窄为「评测运行」，rubric 管理移入新「评测标准」区。
- **兼容**：`legal` 域必须零回归——未注册订阅时等价于「订阅 law-library 全部源」，现有 `/d/legal/*` 与旧菜单 302 后行为一致；未订阅的域检索 fail-closed，不回落到默认库。
- **不在本版范围**：跨库联合检索、本体自动抽取（仍走舰队提案 + 专家确认）、多租户向量物理隔离。
