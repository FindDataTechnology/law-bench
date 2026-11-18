# bench-public-overview Specification

## Purpose
公共 pod 上的匿名只读概览面：让介绍站与外部访客在无凭据条件下读到「已发布本体版本 + 计数 + 分层分布 + as_of」的唯一窄口子。fail-closed 教义不破——豁免刻在一个路径上，其余全部保持 401；语料正文与内部标识永不出门。

## Requirements

### Requirement: 匿名只读概览端点

公共 app SHALL 提供 `GET /api/public/overview` 端点，无需任何凭据可访问（豁免机制见 `public-api-service`），返回 JSON 载荷：`as_of`（数据快照时间）、`ontology_versions`（每个已发布本体版本：`domain_key`、`version`、`digest`、`published_at`、`counts`（实体数、关系数、gold/silver/bronze 分层分布））、`totals`（平台级汇总）。端点 SHALL 纯只读：不写任何表、不触 `last_used_at`、不产生发布或升格副作用。载荷 SHALL NOT 包含语料正文、条款内容、客户身份、内部主机/凭据等非公开标识。版本与 digest 数据 SHALL 来自已发布状态（复用 `knowledge-distribution` 的发布版本记录），不另建账。

#### Scenario: 匿名请求返回概览载荷

- **WHEN** 无任何凭据的请求到达公共 pod 的 `GET /api/public/overview`
- **THEN** 响应 200，载荷含 `as_of`、`ontology_versions`（含 legal v1 的 version/digest/counts）、`totals`，且不含任何语料正文或内部标识字段

#### Scenario: digest 与发布版本对账

- **WHEN** 概览载荷中列出某本体版本
- **THEN** 其 `digest` 与 `published_at` 与分发面已发布版本记录一致（概览是发布状态的只读投影，不是第二发布面）

#### Scenario: 语料正文不出门

- **WHEN** 解析概览载荷全量字段
- **THEN** 载荷不含条款/实体正文内容、评估记录、客户名、API key、内部主机名或路径

### Requirement: 窄豁免与 fail-closed 姿态

匿名豁免 SHALL 只作用于公共 app 上 `bench-public-overview` 挂载的概览路由，经既有 exempt-path 短路机制以 **app 级精确路径注册**（`app.state.extra_exempt_paths`，无前缀无通配）；origin 工作台 app SHALL NOT 注册该豁免且 SHALL NOT 挂载概览路由（同路径在 origin 未注册，匿名不可达——404 而非开放面）。豁免 SHALL NOT 扩展到同前缀其他路径：公共 app 在 `/api/public/` 下 SHALL 注册认证 catch-all，匿名同级请求得 401（构造级认证先于处理器运行）。豁免配置缺失或机制异常时 SHALL 默认拒绝（401），不得静默放开。

#### Scenario: 公共 app 匿名可达、origin 不可达

- **WHEN** 同一路径 `/api/public/overview` 分别以无凭据请求打到公共 pod 与 origin 工作台 app
- **THEN** 公共 pod 返回 200 概览载荷；origin 上该路由未挂载，返回 404（不存在匿名面，也不存在豁免）

#### Scenario: 豁免不蔓延

- **WHEN** 无凭据请求 `/api/public/overview/anything`、`/api/contracts`、`/samples` 等其他公共路由
- **THEN** 一律 401（豁免仅限注册的精确路径）

#### Scenario: 机制异常默认拒绝

- **WHEN** 豁免注册清单加载失败或缺该路径条目
- **THEN** 概览端点对匿名请求返回 401，不回退为放开

### Requirement: 匿名限流

概览端点 SHALL 施加 per-IP 匿名限流（复用既有 `rate_limit.py` 限流器）；超限 SHALL 返回 429 并携带 `Retry-After`。限流 SHALL 独立于认证凭据（匿名与持 key 请求同路径均受保护）；限流状态不落库、进程内即可。

#### Scenario: 超限返回 429

- **WHEN** 同一 IP 在限流窗口内请求概览端点超过配额
- **THEN** 响应 429 且携带 `Retry-After`，载荷不再生成

#### Scenario: 限流不豁免持钥者

- **WHEN** 持有效 API key 的请求超限
- **THEN** 同样 429（限流按调用者计——匿名按 IP、持钥按键前缀——不因持钥豁免）

### Requirement: 如实降级与 as_of 诚实

数据库不可达或发布状态读取失败时，端点 SHALL 返回 503 并携带报因 JSON（`{"error": ..., "reason": ...}`），SHALL NOT 回退陈旧缓存冒充新鲜；`as_of` SHALL 取所读数据快照的时间戳，SHALL NOT 取服务器当前时间凑数。

#### Scenario: 库不可达如实报因

- **WHEN** 概览端点读库失败
- **THEN** 响应 503，body 说明失败原因，不返回任何旧快照数据

#### Scenario: as_of 锚定数据而非时钟

- **WHEN** 数据最后一次发布状态更新早于当前请求
- **THEN** 载荷 `as_of` 等于该数据快照时间，与服务器当前时间无关
