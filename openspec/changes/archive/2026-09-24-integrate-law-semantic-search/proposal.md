# Proposal: integrate-law-semantic-search

## Why

第一批（`link-law-catalog-audit`）解决了"引用名 ↔ 法规身份"的结构化关联，但起草链路仍然无法基于法规**原文**工作：drafter 只有 `contract_search`（合同模板/草案语料），没有法规检索；条文级引用（"民法典第1085条"）也无法解析到具体条文文本。法规库侧已有对外计量 API（law-api.finddatatech.cloud/v1，APISIX key-auth + Lago 计费，搜索结果自带 law_status），接入即可让生成时引法、条文级解析、后续评测核对全部落地，且 law-bench 保持"无向量"——不直连 Qdrant/embedding-svc，法规库换嵌入模型不再波及 law-bench。

## What Changes

- 新增 law-api 客户端：`LAW_API_BASE_URL` / `LAW_API_KEY` / `LAW_SEARCH_ENABLED` 三个环境变量，key 为空或网关不通时功能静默降级（对齐 `ContractSearchTool` 容错模式），起草链路永不为法规检索失败而中断。
- drafter 新增 `law_search` 检索工具（CrewAI BaseTool，与 `contract_search` 并列）：语义检索法规分块，返回带 title/law_status/law_id 的上下文片段。
- 新增条文级引用解析："《民法典》第1085条"式引用 → 法名 hint（复用第一批解析层）→ law_id → 取整部全文 → 本地匹配 `^第X条`（中文/阿拉伯数字均支持，移植 law-rag-pipeline `law-query-api.js` 的 parseCitation/resolveCitation 逻辑，但不移植其 Qdrant scroll 实现）。
- 全文获取走 `GET /v1/laws/{law_id}`，返回的 law_id 一律按不透明字符串处理、不做数字强转（规避 JSONL/Qdrant 已知的字符串类型坑）。
- 接入 runbook：law-api consumer 三步开通（Lago 建客户 → APISIX 发 key → meter-map 加映射，归法规库项目侧）+ 启用前冒烟自检。

不改动：ES/`rag-search` 既有行为、Qdrant/embedding-svc（明确禁止直连）、`law_refs` 派生管线。

## Capabilities

### New Capabilities

- `law-semantic-search`: 通过 law-api 的法规语义检索接入——配置面、降级行为、drafter 检索工具。
- `law-article-citation`: 条文级引用解析——引用串到（law_id, 条文文本）的解析，含条号数字形态归一。

### Modified Capabilities

（无。）

## Impact

- **代码**：新增 law-api 客户端模块与配置；`src/search/rag_tool.py` 旁新增 law_search 工具（或等效位置）并挂入 drafter crew；条文解析模块（依赖第一批的 `clause_law_refs`/解析阶梯）。
- **依赖顺序**：`law_search` 工具可独立实施；条文级解析**依赖 `link-law-catalog-audit` 已实施**（名称解析层是它的输入）。启动条件：第一批审计验证过解析质量。
- **外部**：law-api 网关可用性成为该功能的运行时依赖（降级保护已覆盖）；10 r/s 限流下 compare 高并发场景需退避。
- **运维**：key 发放在法规库项目侧三步流程；law-bench 侧仅环境变量。
