# Design: add-bench-public-overview-tier

## Context

公共 pod 已是 key-only fail-closed（`public_app.py` 构造级 `dependencies=[Depends(get_current_user)]`），且已存在 exempt-path 短路机制（`/healthz` 走的正是这条路，见 `public_app.py` 注释「Exempt from auth checks — the dependency logic short-circuits exempt paths」）。`rate_limit.py` 是现成限流器。`knowledge-distribution` spec 的版本化发布已落库版本/digest/manifest——概览端点是它的只读投影。

## Goals / Non-Goals

- Goals：一个窄豁免匿名端点；载荷最小可公开；限流；如实降级。
- Non-Goals：不建匿名语料读面；不改分发契约；不做缓存层；站点侧工件（Caddy 代理、水合）归 finddata 根 change `add-bench-chain-website`。

## Decisions

### D1. 豁免机制：扩既有 exempt-path 清单，不新造机制
`get_current_user` 依赖里已有 exempt 路径短路。新端点路径 `/api/public/overview` 以**精确字符串**加入公共 app 的豁免清单；origin app（`app.py` 构造同一依赖）不加入——豁免是 app 级配置，不是依赖级全局。备选（新 middleware 放行）被否：两套豁免语义必然漂移。

### D2. 数据源：只读发布状态，不复制账本
`ontology_versions` 直接读分发面发布版本记录（`distribution.py` 的版本表/状态），分层计数复用 promotion 统计查询。若发布状态无现成聚合，允许在 router 内做一次聚合查询，但**不落新表、不建缓存表**——第二账本必然漂移。

### D3. 路径与命名
`/api/public/overview`：`/api/*` 命名空间下无碰撞（现有挂载为 `/api/contracts`、`/api/search`、`/samples`、`/law-info`、`/clauses`）；`public` 前缀明示匿名面。站点同源代理直接用同一路径，不搞双路径映射。

### D4. 限流
复用 `rate_limit.py` per-IP 桶；配额取现有限流默认档（不新设参数），进程内即可——匿名面被打爆的代价是 429，不是数据泄露。持 key 请求同受保护（按 IP，不按身份豁免）。

### D5. as_of 语义
`as_of` = 所读发布状态的最大 `published_at`（或状态表快照时间），绝不 `datetime.now()`。这是 qicai「实时概况带 + as_of，不硬编数字」纪律在后端的对应物。

### D6. 降级
读库异常 → 503 + `{"error": ..., "reason": ...}`。不加 stale 缓存兜底——概览面的可信度全押在「数字永远与发布状态一致」上，stale 回退一次就全毁。

## Risks / Trade-offs

- 匿名面暴露计数（发布版本数、实体规模）→ 已被 C3 契约定为公开发布语义，且不含正文；风险可接受。
- 豁免机制被误改成前缀匹配 → spec 以 Scenario 钉死「豁免不蔓延」+ 测试覆盖 sibling 路径。
- 公共 pod 与 origin 同依赖共享 → 豁免清单必须 app 级注入（D1），实现时以测试锁死 origin 行为。

## Migration Plan

无 schema 迁移。滚公共 pod 镜像即可；origin app 行为零变化（测试锁定）。

## Open Questions

- 站点 Caddy 代理的超时与缓冲参数：由 `add-bench-chain-website` 的 design 定，本 change 不管。
