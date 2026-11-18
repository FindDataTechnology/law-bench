# Tasks: integrate-law-semantic-search

> 前置：`link-law-catalog-audit` 已实施且审计验证过解析质量；§3 起依赖其解析层。§1–§2（law-api 客户端 + law_search 工具）可先行。

## 1. law-api 客户端

- [x] 1.1 新增配置：`LAW_API_BASE_URL`（默认 `https://law-api.finddatatech.cloud/v1`）、`LAW_API_KEY`、`LAW_SEARCH_ENABLED`（默认 false）入 `src/settings.py`，key 为空 = 功能整体不启用
- [x] 1.2 实现客户端模块：`POST /v1/search`（query/top_k，透传 title/law_id/law_status/chunk）与 `GET /v1/laws/{law_id}`（全文 + law_status）；law_id 全程按不透明字符串处理；失败（网络/超时/非 2xx 含 401/429）返回明确错误对象、不抛异常进调用方
- [x] 1.3 降级与退避：429 不激进重试直接降级；所有失败记日志（含响应片段样本）；启用时进程首次调用前跑固定查询冒烟（命中则放行，失败保持降级并 ERROR）

## 2. law_search drafter 工具

- [x] 2.1 实现 `LawSearchTool`（CrewAI BaseTool，双语名/描述对齐 `contract_search` 风格），返回片段带 `[法规/law: title (law_id, 状态/law_status)]` 头
- [x] 2.2 挂入 drafter crew 工具列表（受 `LAW_SEARCH_ENABLED`+key 双重门控；`RAG_TOOL_ENABLED` 语义不变）
- [x] 2.3 端到端验证（真 key：固定查询命中婚姻家庭编解释（一）；定金查询命中民法典586条；关 key/故障降级由 mock 单测覆盖）：真 key 下固定查询（`民法典 离婚后子女抚养费` → 婚姻家庭编解释（一）第42条 类命中）；关 key / 断网重跑起草链路确认零中断

## 3. 条文级引用解析（依赖第一批解析层）

- [x] 3.1 移植 `parseCitation` 语法为纯本地解析器：法名 hint、条号中文↔阿拉伯归一（以 `law-query-api.js` 行为为对照集做单测快照）、款/项子引用保留
- [x] 3.2 实现条文定位：法名 hint → 第一批解析阶梯 → law_id → `GET /v1/laws/{id}` 全文 → `第X条` 边界切分定位；条号越界、名称未解析、全文获取失败三类结果分开上报；全文按 law_id 进程内缓存/批量预取
- [x] 3.3 `law_catalog` 新增条文级结果表（clause_id、law_id、article_ordinal、article_text、status 快照、resolved_via/失败类别），幂等全量重跑，验证不触碰条款本体与 `law_refs`

## 4. 测试与收尾

- [x] 4.1 单测：解析器数字归一边界（快照对照原 JS）、law_id 字符串不强转、三类失败分开、降级路径（mock 网关 401/429/超时）、冒烟门控
- [x] 4.2 runbook：consumer 三步开通流程（法规库项目侧）+ law-bench 侧环境注入 + 冒烟验收标准 + 关停回滚（关开关/清 key）
