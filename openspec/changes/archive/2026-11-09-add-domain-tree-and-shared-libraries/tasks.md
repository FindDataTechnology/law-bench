## 1. 存储层：域树与大库（纯增量）

- [x] 1.1 `ensure_schema` 增 `domains.parent_id / domains.path`（含 `UNIQUE(path)`）与回填：现有 legal → `path='legal'`；验证＝在真实 cell 库副本上跑 `initDb` 后 `select key,path from domains` 返回 `legal | legal`
- [x] 1.2 新增 `libraries / library_sources / domain_library_subscriptions` 三表（含 `UNIQUE(library_key)`、`UNIQUE(domain_id, library_id)`）；验证＝新增 `tests/test_shared_library_store.py` 建库/建源/订阅/重复 key 拒绝全绿
- [x] 1.3 新增 `corpus_chunks`（向量列 + `(library_id, scope_path)` 索引 + `content_hash`）；验证＝迁移脚本在空库建表成功，且 `\d corpus_chunks` 含向量列与两个索引
      ＊实际列类型为 `REAL[]`（部署镜像 `postgres:16-alpine` 无 pgvector 扩展），相似度在 Python 里算，`libraries.backend='array-cosine'` 显式记账；换 pgvector 是模块内局部改动
- [x] 1.4 `knowledge_units` 增 `derived_from JSONB` 并把 `namespace` 语义改为域 path（回填 `'default'`→`'legal'`）；验证＝`select namespace,count(*) from knowledge_units group by 1` 只剩 `legal`
- [x] 1.5 `rubrics` 增 `domain_id NOT NULL / derived_from / fork_diff`，回填现有 2 行为 legal；验证＝`select count(*) from rubrics where domain_id is null` 为 0
- [x] 1.6 订阅解析函数 `effective_sources(domain_path)`：沿路径向上收集、父在前子收窄、只减不加；验证＝单测覆盖「父订阅 3 源 / 子收窄到 2 / 子试图加父未订阅库被拒」三种情况

## 2. 语料与检索：切 pgvector

- [x] 2.1 新增 `src/search/library_index.py`（写块/删块/按库+子树+源过滤检索），幂等键用 `(library_id, doc_path)` + `content_hash`；验证＝单测：同文档两次摄取块数不变
- [x] 2.2 `ingest` 改为按库摄取并写 `scope_path / source_key / doc_path / chunk_seq / meta`；验证＝摄取一个测试源后每块可溯源（源/文档/块序号）
- [x] 2.3 `search()` 增加 `domain_path` 参数并按有效订阅过滤；缺域标识的租户调用拒绝；未订阅域返回显式「未订阅语料」错误态；验证＝单测三态（有匹配/无匹配/未订阅）可区分
- [x] 2.4 检索范围解释接口：返回「每个源来自本域订阅还是继承、被哪次收窄削掉」；验证＝单测断言解释结果与实际过滤所用集合同源（同一函数产出）
- [x] 2.5 ES 路径降级为 fallback（不可用时日志告警而非 500），生产未配 ES 时整条链路走 pgvector；验证＝生产 `/search` 不再出现「搜索后端不可用」

## 3. 本体与评测标准域化

- [x] 3.1 模板 `extends`：保存时校验「继承项不可删除」、实例化前校验继承后的有效词表；验证＝单测：删父项被拒 / 增子项成功且有效词表 = 父 ∪ 子
- [x] 3.2 模板升版不传播：父模板 v2 发布后子模板与实例仍钉 v1，界面提示可升级；验证＝单测 + 模板详情页断言
- [x] 3.3 `knowledge_units` 读取沿路径向上继承、同键本域优先；写入按域 path 落 namespace；验证＝单测：父域 1 条 + 子域同名 1 条 → 子域读到自己那条，子域无同名时读到父域那条
- [x] 3.4 rubric 域化读写 + 引用式继承 + fork 必须写 `fork_diff`；验证＝单测：fork 未带差异被拒 / 带差异成功且 `derived_from` 指向父 rubric
- [x] 3.5 评测运行按域解析 rubric（本域优先、同名覆盖）并记录所用 rubric 的所属域；验证＝单测：子域同名 rubric 生效，运行记录标子域

## 4. 交互：全域运营台 + 域内 8 区

- [x] 4.1 `AREAS` 扩为 8 区（新增 `knowledge`、`eval-standards`，`bench` 收窄为 `eval-runs`），`min_role` 沿用；验证＝按角色渲染的区集合单测（annotator/expert/lead/admin 四种）
- [x] 4.2 L0 全域运营台 `/d`：父子缩进 + 四支柱缺口矩阵 + 缺口筛选；验证＝e2e：造 3 个域（1 缺语料、1 缺 rubric）后页面标出缺口且可筛
- [x] 4.3 「知识库」区：有效取材范围（含继承来源）+ 订阅管理 + 库健康 + **检索框**；验证＝页面展示某子域的源清单并标明「继承自 legal」；检索命中带库/源/定位/相似度，未命中与检索失败分别明示（`tests/test_knowledge_search.py` 6 条）
- [x] 4.4 「评测标准」区：本域 rubric + 继承自父域分组 + fork 入口（要求填差异）；验证＝e2e：fork 一条后出现在本域分组且带差异摘要
- [x] 4.5 「评测运行」区：历史运行 + 结果，按域过滤；验证＝造两条不同域的运行，页面只显示本域
- [x] 4.6 新建细分域向导：选父域 → 预览继承词表 → 勾选订阅源 → 生成缺口清单 → 提交创建；验证＝e2e：5 步走完在 L0 出现新域，缺口如实
- [x] 4.7 批量派单（按缺口筛选后派给负责人/舰队）需二次确认，页面加载零写操作；验证＝`tests/test_dispatch.py`：加载 `/d?gap=` 与确认页后 `authoring_tasks` 仍为 0；确认后按域数建单；二次确认不重复（报 skipped）

## 5. 旧路径收敛与兼容

- [x] 5.1 旧 11 条入口收敛：工具页并入其所属区（知识库/评测标准/评测运行）的「更多工具」入口，`/d/<域>/bench` 保留 302 → `/eval-runs`；验证＝`tests/test_domain_areas_http.py::test_legacy_bench_redirects_to_eval_runs` 断言 302 且目标 200
      ＊与原计划的差异：不是 11 条全 302，而是「迁到所属区 + 仅 bench 302」——顶栏已被三层导航替代，302 一条空页反而更差
- [x] 5.2 顶栏只保留三层导航（全域/我的域/域内区），旧平铺菜单移除；验证＝e2e 断言顶栏不再出现旧菜单项
- [x] 5.3 legal 域零回归：`/d`、`/d/legal`、六区页面、旧路径全 200/302；验证＝e2e 全量走查通过

## 6. 收口

- [x] 6.1 `openspec validate add-domain-tree-and-shared-libraries --strict` 通过
- [x] 6.2 全量 pytest 通过：1458 passed / 60 skipped（基线 1396 → 无回归）；e2e 走查见 5.3
- [x] 6.3 生产落地：`sha-5cccec0` 已滚（Argo automated），pod 1/1 Ready，`/healthz` 200；回滚锚 `sha-2180036` 写在 `deploy/deployment.yaml` 注释里
- [x] 6.4 验收报告：`reports/2026-11-08-real-corpora-wired.md`（盘点表、空间一致性 cos 值、源分区合计、页面状态码与检索命中、单测名）

## 7. 真实语料接入（外部向量库）

盘点结论（2026-11-08 实测，非推断）：法规线主检索在 Qdrant（`law_chunks_v2`，364,916 点，
1024 维 Cosine，payload 带 `category/law_type/law_status`）；文字引擎 `fd_text` 在
`100.64.0.10` 的 pgvector 0.8.7（gov 2,160 / news 2,942 / papers 82 / screenplay 2,305，
`vector(1024)`，Qwen3-Embedding-8B + MRL 1024）；`fd-open-data-mcp` 是 384 维 MiniLM；
`fd-legal-kg`（Graphiti+FalkorDB）未部署；**wire 本体层不是向量库**（实体/关系是版本化行）。

- [x] 7.1 `libraries.backend` 扩到四个取值（`array-cosine` / `pgvector` / `qdrant` / `pgvector-external`），部署表的 CHECK 只有旧两值会拒新库 → 就地 DROP 再 ADD（幂等）；验证＝`tests/test_library_schema_legacy.py` 在真实旧形状上重放 schema 不报错
- [x] 7.2 `libraries.location` 只存**环境变量名**（`{"url_env": "QDRANT_URL"}` / `{"dsn_env": "FDTEXT_DATABASE_URL"}`），查询时解析，缺失报明变量名；验证＝`test_location_never_stores_a_value_only_a_name` / `test_resolve_location_names_the_missing_variable`
- [x] 7.3 `src/search/embedders.py` 按 `embedding_model` 路由（0.6B→集群 `POST /embed`；8B→网关并显式 `dimensions`）；验证＝`test_two_1024_spaces_are_not_interchangeable` / `test_mrl_model_requests_explicit_dimensions` / `test_wrong_dimensions_raise_instead_of_degrading`
      实测空间一致性：Qdrant 存量 vs 集群重算 cos=0.999894；fd_text 存量 vs 网关 8B+dimensions=1024 cos=0.999864，不带 dimensions 得 4096 维、cos=0.50
- [x] 7.4 Qdrant 检索适配（payload 过滤 + `points/count`）+ 命中归属从 payload 反推；源规则支持多值 `any`（「地方性法规」与「地方法规」是同一类的两种写法，166,428 点）；验证＝`test_qdrant_search_sends_the_filter_and_maps_hits` / `test_a_source_may_cover_several_spellings_of_one_class`
- [x] 7.5 外部 pgvector 适配（`<=>` + where 过滤 + 标识符校验）；验证＝`test_library_external_backends.py` 覆盖过滤条件构造与不可达报错
- [x] 7.6 缺口矩阵按外部库自数（`count_scope`），连不通报 error 不报 0；验证＝`test_count_scope_counts_the_remote_store` / `test_unreachable_store_reports_an_error_instead_of_zero`
- [x] 7.7 生产登记 `law-library` 并让 `legal` 订阅；验证＝`scripts/register_libraries.py` 自检 `ok=True`：7 个源合计 364,916 = 整库计数；`estate.matrix` 得出 `legal knowledge={libraries:1, sources:7, chunks:364916} gaps=[]`
- [x] 7.8 端到端检索实证（生产 pod 内）：`建设工程价款优先受偿权` → 三部司法解释 0.7617/0.7507/0.7417，源归属 `judicial`；`违约责任如何认定` → 民法典/民法通则
- [x] 7.9（裁决：**只登记、不订阅**，2026-11-09）`text-library` 已登记：backend `pgvector-external`、1024、`Qwen/Qwen3-Embedding-8B`，四源各对应一张表（gov/news/papers/screenplay）；secret `law-bench-fdtext` 只含一个键 `FDTEXT_DATABASE_URL`（从 fd-prod 复制）。验证＝`register_libraries.py --only text` 输出 `counts {gov:2160, news:54032, papers:82, screenplay:2305}` 且 `subscribers: 0`；`legal` 的 `knowledge` 仍为 `{libraries:1, sources:7, chunks:364916}`，`effective_sources` 只含 `law-library`
      ＊真要订阅检索时还需 `LIBRARY_EMBED_GATEWAY_KEY`（8B 走网关 + 显式 `dimensions=1024`），缺键会明确报错而非静默降质
      ＊`news` 已从 11-08 的 2,942 涨到 54,032——该垂域在持续摄取，写下的任何数字都是快照
- [x] 7.10 控制台补「登记外部库」入口：`/admin/libraries`（admin 独占）建库/加源/订阅；外部库只填环境变量名，表单里没有 DSN/口令字段；`match` 解析失败拒存（空规则=整库，手滑会放大范围）；验证＝`tests/test_admin_libraries.py` 8 条
- [x] 7.11 语料声明可校验：`source_types` 支持 `library:<lib>/<src>` 绑定真实库源；保存模板时校验引用存在（库/源不在即拒）；知识区显示「声明 vs 现状」（已覆盖 / 未覆盖+原因 / 自由文本标签不判健康）；验证＝`tests/test_corpus_declarations.py` 10 条
