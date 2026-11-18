# Design: integrate-law-semantic-search

## Context

第一批 `link-law-catalog-audit` 建立了目录副本与名称解析层。法规库侧对外有计量 API：`https://law-api.finddatatech.cloud/v1/`（APISIX key-auth，10 r/s，Lago 按 2xx 计费），端点 `POST /v1/search {query, top_k, filters, group_by_law, expand}` 与 `GET /v1/laws/{law_id}`（整部全文拼装 + law_status），搜索结果每条自带 law_status。法规库嵌入层已从 bge 512 维换到 Qwen3-Embedding 1024 维一次——内部参数（模型/维度/pooling/Qdrant 拓扑）被网关挡住，law-bench 不应感知。条文级解析有现成轮子：law-rag-pipeline `cluster/law-query-api.js` 的 `parseCitation`/`resolveCitation`（法名 hint + 条号 → chunk 匹配 `^第X条`，中/阿数字都处理过），但其 resolve 依赖 Qdrant scroll——只移植解析逻辑，不移植检索实现。

## Goals / Non-Goals

**Goals:**

- law-bench 通过 law-api 获得法规语义检索与全文获取，自身保持"无向量"（不配模型、不配维度、不直连 Qdrant/embedding-svc）。
- drafter 起草时能引到带时效状态（law_status）的法规原文片段。
- "民法典第1085条"式引用可解析到 (law_id, 条号, 条文文本, status)。

**Non-Goals:**

- 不做 law-bench 内嵌任何 embedding（fastembed/bge/Qwen 都不放进来）。
- 不改 ES/`rag-search` 既有行为；law-api 不可用不构成任何现有功能的故障。
- 不做"修改、废止的决定"正文废止清单解析（后续独立增强）。
- 不在本变更把条文级核对挂进评测 rubric（评测接入另行变更）。

## Decisions

### D1: 只走 law-api，不直连 Qdrant/embedding-svc

备选（直连 100.64.0.9:6333 + embedding-svc）省一跳网络，但把维度/模型/pooling 编进 law-bench——历史上换过一次嵌入模型，直连方案每次换模都要改代码并重做自检索校验。走 API 后这些内部细节归法规库项目；且计量/限流本来就在网关侧项目管（用户既定分工）。集群内直连仅留作 API 链路被证明确实碍事时的后备，不作为首选。

### D2: 配置面三个环境变量 + 静默降级

`LAW_API_BASE_URL`（默认 `https://law-api.finddatatech.cloud/v1`）、`LAW_API_KEY`（空 = 不注册工具、零请求）、`LAW_SEARCH_ENABLED`（默认关）。任何失败（网络/超时/401/429）返回空串、记日志，异常绝不进 crew——完全对齐 `ContractSearchTool`（`src/search/rag_tool.py`）的容错契约。限流退避：客户端对 429 不做激进重试，直接降级为空结果（起草是低 QPS 场景，compare 并发 ≤8 也在 10 r/s 内；真撞限流说明该加 key 配额而不是客户端硬顶）。

### D3: law_search 工具形态与返回契约

CrewAI `BaseTool`，名字/描述双语对齐 `contract_search` 风格，挂入 drafter crew 的工具列表（`RAG_TOOL_ENABLED` 语义不变，law 工具由自己的开关控制）。返回片段格式：`[法规/law: {title} (law_id={law_id}, 状态={law_status})]\n{chunk_text}`——law_status 进上下文，让 drafter 引到的每条法规自带时效信号，天然避开已废止法。

### D4: 条文级解析 = 移植 parse 的"语法"，替换 resolve 的"数据源"

- **解析（纯本地，零网络）**：移植 `law-query-api.js` 的 `parseCitation` 语法——法名 hint 提取（书名号内/裸法名 + `第…条` 锚点）、条号中文↔阿拉伯归一（含"一千零八十五"复合数字）、款/项子引用保留。
- **定位（换数据源）**：原实现 scroll Qdrant chunks 匹配 `^第X条`；本实现改为 法名 hint → 第一批解析阶梯得 law_id → `GET /v1/laws/{law_id}` 取整部全文 → 本地按 `第X条` 边界切分定位条号。全文获取失败与条号越界是两种独立失败，分开上报。
- **law_id 一律不透明字符串**：来自 API 的 id 不做数字强转；与本地目录副本 join 时显式声明比较语义（副本侧整数 ↔ API 侧字符串，在 join 边界统一转字符串比较）。
- **全文缓存（可选）**：同一部法在一次批量解析里会被引多次，进程内 LRU 或按 law_id 的会话级缓存即可，不建持久缓存表——目录副本刻意不含全文，保持轻量。

### D5: 存储挂接第一批的链接层

条文级结果表挂在 `law_catalog`（clause_id、law_id、article_ordinal、article_text、status 快照、resolved_via、失败类别），与名称级 `clause_law_refs` 同族：幂等全量重跑、不碰条款本体。审计报告后续版本可展示"引用精确到条"的覆盖率。

### D6: 启用前置：冒烟自检

启用（`LAW_SEARCH_ENABLED=true` 且 key 非空）时进程首次调用前跑一次固定查询冒烟（如 `民法典 离婚后子女抚养费` 应命中婚姻家庭编解释），失败记 ERROR 日志并让本进程内功能保持降级，不阻断启动。用户要求的"自检索校验"精神保留，但校验的是 API 链路而非向量语义（那已归网关侧）。

## Risks / Trade-offs

- [网关单点：law-api 或 APISIX 挂了则检索降级为空] → D2 静默降级保证起草/评测不中断；网关可用性归法规库项目侧 SLA。
- [10 r/s 限流撞顶（compare 并发 + 条文批量解析的全文拉取）] → 全文按 law_id 去重 + 进程内缓存批量预取；仍顶配额则升 key 配额（网关侧动作）。
- [移植 parseCitation 的数字归一边界情况（"一百零五" vs "一百五"）] → 以原 JS 实现为对照集做单测快照，不重新发明。
- [law-api 响应结构未来变化] → 客户端收敛在单一模块，响应解析失败按降级处理并在日志中带响应片段样本。
- [名称解析层错误传播到条文级] → 条文级启动前置是第一批审计验证通过；条数越界/名称未解析分开上报，不静默吞。

## Migration Plan

配置默认关闭（`LAW_SEARCH_ENABLED` 缺省 false），合入即部署也不改变任何现有行为。开通步骤：法规库项目侧三步 onboarding（Lago 建客户 → APISIX 发 key → meter-map 加映射）→ law-bench 环境注入 key 并开开关 → 冒烟自检通过。回滚 = 关开关/清 key，零数据影响。

## Open Questions

- `POST /v1/search` 的 `filters`/`group_by_law`/`expand` 参数在条文定位场景的取舍（实现期按需启用 `group_by_law`，不阻塞设计）。
- 条文级结果是否反哺 web 合同页展示（条款旁挂条文原文链接）——看第一批 UI 反馈，另行小变更。
