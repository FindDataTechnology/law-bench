# Proposal: add-bench-public-overview-tier

## Why

介绍站（finddata 根 change `add-bench-chain-website`）的门 B 需要「当场可试」的真证据，而 bench 今天全认证、无匿名口子：`public_app.py` 全路由继承 `get_current_user`，MCP 也要求 Bearer/X-API-Key。本 change 在公共 pod 上开一个**窄豁免的匿名只读概览端点**，让站点能活水合「已发布本体版本 + 计数 + 分层分布」——这是 bench 与 wire（柏讯）分发链的交集，也是站点唯一的活证据。先例：教育线 `add-education-public-read-tier`。

## What Changes

- 新增匿名只读概览端点 `GET /api/public/overview`（挂载于公共 app `public_app.py`）：返回 `as_of`、已发布本体版本清单（domain_key、version、digest、published_at、实体/关系计数、gold/silver/bronze 分层分布）、平台级汇总；**不含语料正文、不含内部标识**。
- 豁免面收窄：仅该路径在**公共 app**上豁免认证（复用现有 exempt-path 短路机制）；origin 工作台 app 不豁免，匿名仍 401。
- 匿名请求按 per-IP 限流（复用 `rate_limit.py`），超限 429；端点纯只读，无任何写副作用（不触 `last_used_at`）。
- 如实降级：库不可达 → 503 带报因，不回退陈旧缓存冒充新鲜；`as_of` 取数据快照时间而非服务器当前时间。
- 不改 `knowledge-distribution` 契约（端点只读已发布状态，不产生第二发布面）。

## Capabilities

### New Capabilities

- `bench-public-overview`: 公共 pod 上的匿名只读概览面——载荷契约、窄豁免与 fail-closed 姿态、限流、如实降级。

### Modified Capabilities

- `public-api-service`: 「Key-only auth posture on the public pod」需求修订——在 key-only 姿态上刻入唯一窄豁免（仅 `bench-public-overview` 挂载的概览路由），其余路径仍 401。

## Impact

- `src/web/public_app.py`：挂载新 router + exempt-path 注册。
- `src/web/routes/`：新增 `public_overview.py`（载荷组装，复用 distribution 已发布版本状态与 promotion 分层计数，不重复建账）。
- `src/web/deps.py` / rate limit：豁免清单与 per-IP 限流复用。
- 站点侧（Caddy 同源代理、水合契约）由 finddata 根 change `add-bench-chain-website` 承接，本 change 不含站点工件。
- 部署：公共 pod 滚版（argocd 既有线）；无 schema 迁移。
