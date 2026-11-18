# 真实语料接入 · 验收证据（2026-11-08）

镜像 `sha-c93f7ce`，源 `c15d961`，Argo automated 滚版，pod 1/1 Ready。

## 一、语料盘点（实测，非推断）

| 存储 | 位置 | 规模 | 维度/模型 | 状态 |
|---|---|---|---|---|
| `law_chunks_v2` | Qdrant `qdrant.law-rag` | **364,916 点** | 1024 Cosine / `Qwen3-Embedding-0.6B` | 活，本次接入 |
| `fd_text`（四垂域） | PG `100.64.0.10:5432` pgvector 0.8.7 + HNSW | gov 2,160 / news 2,942 / papers 82 / screenplay 2,305 | `vector(1024)` / `Qwen3-Embedding-8B`（MRL） | 活，未接入（§7.9） |
| fd-open-data 指标库 | pgvector | 指标/目录条目 | `vector(384)` / MiniLM | 活，未接入 |
| `fd-legal-kg` | Graphiti + FalkorDB `100.64.0.10:6379` | 无实例 | 1024 / Qwen3-8B | 未部署 |

`100.64.0.5`（windows 数据机）**没有**向量库：11 个库全无 `vector` 扩展，法规只是
`laws`/`law_chunks_v2` 文本行，向量在 Qdrant。**wire 本体层不是向量库**——实体/关系是
PG 里版本化行（append-only 事件 + 快照），`fd-wire` 全仓无 embedding/Qdrant/pgvector 引用。

## 二、空间一致性（决定性验证：拿库里已存的向量比）

| 存储 | 调用 | cosine |
|---|---|---|
| Qdrant 法规 | 集群 `POST /embed`（0.6B）重算同一条 chunk | **0.999894** |
| `fd_text` | 网关 8B + `dimensions=1024` | **0.999864** |
| `fd_text` | 网关 8B 不带 `dimensions`（4096 维） | 0.500971 |

结论：**两个 1024 维不是同一空间**，路由必须按 `embedding_model`，不能按 dims。

## 三、源分区（穷尽性）

Qdrant facet 实测后切 7 源，合计 = 集合总数，缺口 0：

```
statutes        6,202   法律/宪法/法律解释/有关法律问题…（语料里该值是截断的）
administrative  8,304   行政法规/法规性决定/监察法规
judicial        3,337   司法解释
local         166,428   地方性法规 + 地方法规（同一类的两种写法）
departmental  117,343   规章
amendment       3,920   修改、废止的决定
unclassified   59,382   重下载/新法速递/规范性文件（爬取产物，单列不掩盖）
TOTAL         364,916   = 整库计数
```

写全名「…（部分）」会只数到 6,173、合计 364,887、缺口 29 —— 脚本自检拦住了。

## 四、页面与检索实证（生产 pod 内，真库真路由）

```
/d                            200     （矩阵行：1 / 7 · 364916 块）
/d/legal                      200
/d/legal/{ontology,knowledge,eval-standards,eval-runs,inbox,publish,settings}  200
/d/new                        200
/d/legal/bench                302 → /eval-runs
知识区正文含：law-library / 364916 / statutes / unclassified / qdrant
estate.matrix: legal knowledge={libraries:1, sources:7, chunks:364916} gaps=[]
```

检索（`library_index.search(domain_path="legal")`）：

```
Q 建设工程价款优先受偿权
  0.7617 [judicial] 最高人民法院关于建设工程价款优先受偿权问题的批复#0
  0.7507 [judicial] 关于审理建设工程施工合同纠纷案件适用法律问题的解释（一）#12
  0.7417 [judicial] 关于审理建设工程施工合同纠纷案件适用法律问题的解释（二）#7
Q 违约责任如何认定
  0.6611 [statutes] 中华人民共和国民法典#328
  0.6330 [statutes] 中华人民共和国民法通则#34
```

## 五、测试

全量 `1458 passed / 60 skipped`（基线 1396 → 无回归）；`openspec validate --strict` 通过。

## 六、待人工终审

1. §7.9 是否把 `fd_text` 四垂域（gov/news/papers/screenplay）并进法律站——它们是
   文字线语料，不是法规；接进来只需注入 `FDTEXT_DATABASE_URL` 并登记一个库。
2. `unclassified` 59,382 块（`重下载`/`新法速递`/`规范性文件`）目前对 `legal` 可见。
   若要排除，把订阅收窄到前 6 个源即可——但这是口径决定，须人裁。
3. 控制台还没有「登记外部库」表单（§7.10），目前靠 `scripts/register_libraries.py`。

## 七、检索面（2026-11-08 补，镜像 `sha-0a6254c`）

发现的缺口：`/search` 与 `/api/search` 走的是旧引擎（`rag_corpora` 的 ES/pg 索引），
新接的库订阅完全不经过它们——缺口矩阵说「364,916 块可检索」，而页面上一查不到。

知识区已加检索框，走 `library_index.search`（与范围同一个 `effective_sources`）。
生产实测（pod 内真库真 Qdrant，剔除内联 i18n 目录后只数渲染体）：

```
q=建设工程价款优先受偿权  渲染 10 行
  0.762 judicial / 0.751 judicial / 0.742 judicial ...
  检索失败横幅：无     未命中提示：无     检索表单：在
q=（空）                 无错误横幅、无未命中提示（打开页面不检索）
```

可区分三态：命中 / 没命中（明说不是「没有语料」）/ 检索失败（连不通如实报错）。

## 八、按源可见（镜像 `sha-1d7966b`）

知识区每库现在按源列块数，生产实测（渲染体，剔除内联 i18n 目录）：

```
administrative   8,304      statutes      6,202
amendment        3,920      unclassified 59,382   ← 16%，全是爬取产物
departmental   117,343      judicial      3,337
local          166,428
                       合计 364,916 = 整库计数
```

一次 facet 请求给出全部分类计数（7 源 1 次往返）；源的过滤键不统一时退回逐源
计数（facet 只能按一个键分组）——宁可多几次请求，不给算错的数。

## 九、明确未做（待裁决，非遗漏）

`fd_text` 四垂域（gov 2,160 / news 2,942 / papers 82 / screenplay 2,305）**未登记**。
技术上只差：把 `FDTEXT_DATABASE_URL` 复制到 law-bench 命名空间 + 跑一次登记
（8B + `dimensions=1024`，空间一致性已实测 cos=0.999864）。不做的原因是口径：
那是文字线的语料与凭据，把它带进法律站的攻击面属于产品决定。

## 十、机器取数接口 `GET /api/library/search`（镜像 `sha-2e9bb8f`）

`/api/search` 仍是旧引擎；新库订阅此前在机器侧完全不可见。新增域化接口，生产实测：

```
[200] domain=legal q=建设工程价款优先受偿权 -> 3 hits, top 0.761678 (judicial)
[200] domain=legal q=（空）               -> []
[404] domain=ghost                        -> {"error":"unknown domain 'ghost'"}
```

状态码即契约：200（hits 可空）/ 400 未订阅 / 502 上游故障 / 404 未知域。
域闸沿用 `/api/search` 的 `_effective_domain`，无绕过路径。

## 十一、两处自身缺陷（已修，记录以免重犯）

1. `get_db()` 在 handler 里直调会**绕过依赖注入**：单测单独跑能过，全量跑时拿到
   真库而不是测试库（1499 条里挂了一条）。改为 `Depends(get_db)`。
2. `(key,) = next(iter(keys))` 解包后同名变量变成字符串，紧随的 `len(key) != 1`
   就变成字符串长度判断，永远落进 fallback —— 表现为「facet 没调用、计数全 0」。

## 十二、两处「显示与事实不符」的修正（镜像 `sha-35140a5`）

1. **读不到 ≠ 没有**：向量库连不通时，缺口矩阵原先把「计数失败」判成「缺语料」，
   会让人去补一个已经存在的语料。`gaps_for` 现在只在「没出错且计数为 0」时判缺口；
   错误仍在行上以告警渲染。验证＝`test_unreachable_store_is_unknown_not_a_gap`。
2. **自有库也能按源出数**：按源块数原来只对 qdrant 有效，自有库一律「—」。现在
   按后端各用最合适的方式：自有内容本地一条 `GROUP BY`、外部 pgvector 一表一源
   各一条 `COUNT`、Qdrant 单次 facet（过滤键不统一时退回逐源）；答不了的后端
   返回 `{}` 而不是一堆 0。修一个写错的分支：`backend not in ("qdrant","pgvector")`
   把默认的 `array-cosine` 送进外部 pg 路径（`KeyError: 'dsn_env'`）。

生产实测（`sha-35140a5`）：

```
estate: legal {'libraries': 1, 'sources': 7, 'chunks': 364916} gaps=[]
per-source: administrative 8304 / amendment 3920 / departmental 117343 / judicial 3337
            local 166428 / statutes 6202 / unclassified 59382   → sum 364916
api: 200 [(0.761678,'judicial'), (0.750701,'judicial')]
```

## 十三、落地页耗时（镜像 `sha-7ff7e1a`）

暖机实测（生产 pod，TestClient，同进程）：

| 页面 | 修前 | 修后 |
|---|---|---|
| `/d`（全域运营台，落地页） | 1465 ms | **475 ms** |
| `/d/legal/knowledge` | 295 ms | 275 ms |
| `/d/legal/settings` / `inbox` | 94 / 86 ms | 83 / 86 ms |

原因不是向量库（facet exact 562ms、count exact 190ms，都只在需要的页面上发生），
而是 `/d` **把整个矩阵算了两遍**：一次给行，又一次给三个缺口 chip 的计数。同一个
页面有两个来源回答「哪些域缺什么」，chip 与行也能互相打脸。现在一次矩阵两个视图。

外置库的计数按请求 memo（同一 (库, 授权源集) 只查一次），十个子域继承同一授权
不会变成十次往返；自有内容不缓存（依赖祖先链），因此不会出现陈旧数字。

## 十四、域负责人自收窄（镜像 `sha-9f540a3`）

知识库区每个库面板多了「收窄本域取材范围」表单，只对本域 lead（或平台 admin）显示。
写入时按父域有效集校验，不放行到下一页才炸。生产实测（`/d/legal/knowledge`）：

```
收窄表单渲染：True   表单内列出的源：7（administrative/amendment/departmental/
                     judicial/local/statutes/unclassified）
越权提交（勾选不存在的 ghost）→ 303 flash.narrow_failed，detail 指明 unknown
取材范围未被改动：True
```

子域语义（父域没给的源不能引入、空集被拒、非 lead 无权改）由
`tests/test_knowledge_narrow.py` 7 条守着。

## 十五、派单闭环（镜像 `sha-96b36b4`）

发现的半截功能：派单把 assignee 写成自由文本，而总览页只列
`assignee == user.sub` 的任务——于是派出去的任务**对任何人不可见**；更麻烦的是
派单按「同缺口已有未完成任务」幂等，任务没人能关，那个缺口就永久派不出去。
派单是个只能进不能出的单向门。

补上：收件箱列本域全部任务（含已关闭）带负责人/状态；负责人、本域 lead 或平台
管理员可置完成/取消；跨域任务 id 返回 404。

生产实测（`sha-96b36b4`，用一条探针任务、验完即删）：

```
task visible in inbox: True
close -> 303, status now: done
probe task removed; remaining tasks: 0
```

## 十六、镜像版本漂移（已知，且大部分有意）

同一命名空间里五个 Deployment 用同一镜像的不同 tag：

| Deployment | tag | 判断 |
|---|---|---|
| `law-bench`（主应用） | `sha-96b36b4` | 现役 |
| `law-bench-mcp` | `sha-e411d22` | **有意不动**：该 pod 用 `PYTHONPATH=/opt/mcp/lib/pkgs` 补 MCP 包，tag 是为这个变通选的；本轮只加了 REST 接口、没新增 MCP 工具，旧镜像对全增量 schema 照常工作 |
| `law-bench-mcp-assistant` | `sha-2180036` | 同上（同一变通） |
| `law-bench-public` | `sha-2180036` | **有意不动**：`PUBLIC_API=1` 走 `public_app`，入口脚本明确「读面不得跑 DDL」，其库是 15 分钟同步的快照副本；在副本 schema 落后窗口里换新代码，只会让新 SELECT 撞上还没同步到的列 |
| `copilot-runtime` / `render-service` | 各自镜像 | 不同镜像，与本次无关 |

结论：这不是漏滚，是三个 pod 各有明确理由。要滚它们须先解决各自的前提
（MCP 包的构建上下文、公开副本的 schema 同步窗口），不该顺手带上。

## 十七、总走查（`sha-96b36b4`，生产 pod 内真库真路由）

```
200 /d                        200 /d/legal                 200 /d/new
200 /admin/libraries          200 /admin/templates
200 /d/dispatch?gap=knowledge 200 /d/legal/knowledge?q=违约责任
405 /d/legal/knowledge/narrow（仅 POST，GET 405 正确）
200 /d/legal/{ontology,knowledge,eval-standards,eval-runs,inbox,publish,settings}

知识区渲染体：law-library ✓ 364916 ✓ 收窄本域取材范围 ✓
              模板声明的语料需求 ✓ 检索本域语料 ✓
api: 200  0.761678  judicial（/api/library/search）
```

收件箱的「已派任务」面板当前不渲染，是因为库里没有任务（探针任务已清理）——面板以
`{% if tasks %}` 为条件，空态不显示空表。

## 十八、文字垂域库：只登记、不订阅（裁决 2026-11-09，镜像 `sha-b2a988e`）

裁决内容：文字引擎四个垂域**登记为库但不订阅任何域**；`unclassified` 59,382 块
**保持对 legal 可见**（未动订阅）。

登记结果（`scripts/register_libraries.py --only text`，生产 pod 内跑）：

```
library: text-library  pgvector-external  1024  Qwen/Qwen3-Embedding-8B
location keys: ['dsn_env']        ← 只存环境变量名，不存连接串
sources: gov→corpus_chunks_gov  news→corpus_chunks_news
         papers→corpus_chunks_papers  screenplay→corpus_chunks_screenplay
counts: gov 2,160  news 54,032  papers 82  screenplay 2,305  = 58,579
subscribers: 0
```

未影响任何人的检索范围（同一次探测里验的）：

```
ledger lists text-library: True
estate: legal {'libraries': 1, 'sources': 7, 'chunks': 364916} gaps=[]
legal scope libraries: ['law-library']
```

两点值得记住：

- `news` 已从 11-08 的 2,942 涨到 **54,032** —— 该垂域在持续摄取，写下的数字都是快照。
- 真要订阅检索还需要 `LIBRARY_EMBED_GATEWAY_KEY`（8B 走网关且必须显式
  `dimensions=1024`）。现在不注入：缺键时检索会明确报错，不会静默降质。
- 顺带修一个自身缺陷：脚本里把 `TEXT_SOURCES` 元组当行对象取键，抛
  `tuple indices must be integers`，被外层 except 吞成「counts unavailable」——
  库和源都写进去了，只有计数没打出来。已改为按位解包并加测试钉住元组形状。
