# 设计：知识发布-拉取分发契约

总纲：`docs/knowledge-platform-blueprint.md`（C3，§六分发契约）。C1/C2 已上 spec：`ontology-template`/`domain-workspace`/`expert-authoring` + web-rbac 域作用域。

## D1 发布内容 = 域 namespace 的 KU 全量投影，快照独立成表

发布读 `authoring_list_units(conn, domain_key=..., include_deleted=False)` 语义的 KU 全量（实体=entity_types 词表内各 kind；关系=relationship_kinds 词表内各 kind，键沿 `relationship_external_key` 约定），落**独立快照表**（manifest JSONB 整体冻结），而非引用 KU 行——理由：

- 快照不可变是 spec 硬要求：KU 是活数据（专家继续改），快照必须与后续编辑解耦；
- 「指定期历史版本逐字节一致」要求 manifest 自足，不做运行时拼装；
- 消费者解包逻辑最简单：一份 JSON 即全量。

```
ontology_publications  id, domain_id FK, version INTEGER NOT NULL, digest TEXT NOT NULL,
                       manifest JSONB NOT NULL, changelog JSONB NOT NULL,
                       published_by TEXT NOT NULL, published_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                       UNIQUE (domain_id, version), UNIQUE (domain_id, digest)
                       —— 无 UPDATE/DELETE 路径（append-only，沿 authoring_events 纪律）
distribution_consumers id, name TEXT NOT NULL UNIQUE, domains TEXT[] NOT NULL（域 key 数组）,
                       token_hash TEXT NOT NULL UNIQUE, created_by TEXT NOT NULL,
                       created_at, revoked_at TIMESTAMPTZ
```

digest 规范化（沿 wire 0049 模式）：manifest 规范 JSON（`sort_keys=True`、分隔符紧凑、UTF-8）的 sha256；**生成时间戳/发布者不进 manifest**（保证同内容同 digest）；版本号也不进 manifest（digest 只锚内容）。

## D2 发布判定与幂等

`publish_domain(conn, *, domain_key, published_by)`：
1. 域存在 + 发布者域内 lead（或平台 admin）——执法在 web 路由层（`require_domain_role("lead")` 两道序贯），内核只做数据判定；
2. 收集域内词表内全部 KU（实体+关系，排除软删）；**空域拒绝**（spec 场景）；
3. 构造 manifest：`{domain, template_version, entity_types/relationship_kinds（锚定词表快照）, entities:[...], relationships:[...]}`（KU 字段裁剪为契约面：kind/external_key/body/tier/sensitivity（tags 内）/attrs/关系 from/to）；
4. 算 digest；同域已有同 digest 行 → 返回既有版本（幂等，不 INSERT）；
5. 否则 version=max+1，changelog=与上一版的 diff（见 D3），INSERT。

## D3 changelog 生成

与同域上一快照的 manifest 做键控对比（实体按 external_key、关系按键约定）：
- `added`：新键条目；`removed`：消失键条目；`changed`：同键但 body/tier/sensitivity/attrs 任一变 → 记字段级摘要 `{field: {before, after}}`；
- 首版 changelog = `{"initial": true, counts: {...}}`（spec：首版记初始清单）；
- changelog 也进快照行（随快照冻结，历史版本 changelog 不随后续发布改写）。

## D4 拉取面鉴权三态

`GET /api/v1/distribution/{domain_key}/ontology?version=N&format=json|yaml`：

```
X-Consumer-Token 缺失        -> 401（报明缺凭据）
sha256(token) 无行            -> 403（未登记）
行存在但 revoked_at 非空      -> 403（令牌已吊销）
domain_key 不在 domains 数组  -> 403（该域不在绑定范围）
通过                          -> 200（version 缺省=最新；无任何发布 -> 404 报明）
```

- 路由挂 `src/web/routes/distribution.py`（**不经 Logto**：该 router 不依赖 `get_current_user`；`app.py` include；不挂 public_app）；
- yaml 格式：不新增依赖则手写最小 YAML 序列化器？——pyproject 现无 PyYAML；**裁决：加 `PyYAML` 依赖**（成熟、格式正确性值得），spec 双格式是契约；实现时确认 uv 环境可装；
- 载荷实体字段含 `tier` 与 `sensitivity`（sensitivity 取 KU tags——C2 创作未单列 sensitivity 字段，发布面从 `tags.sensitivity` 读取，缺省 null 如实）。

## D5 与既有面关系

- **wire-connector 零改动**：升格-回写环不动；本 change 只增发布-拉取。wire 侧拉取客户端是 fd-wire 仓姊妹 change（消费本契约）；
- **bench-platform 条款修订**：delta 以 MODIFIED 需求重述「柏讯实体升格契约」——wire 降为 seed 原料源，发布权威在平台，回写环语义保留；同步时整条替换主 spec 该需求（3 个 scenario 全量替换）；
- **域自由闸**：`distribution.py` 在 src/bench/ 下，零法律词表 token；
- **注册点**：两表进 `WORKSPACE_SCHEMA` + `conftest._ALL_TABLES`（沿 C1/C2 三件套）。

## D6 风险

- 风险①：`TEXT[]` 数组列 vs JSONB——选 `TEXT[]`（pg 原生 `= ANY` 查询直觉）；绑定域变更=整组替换（登记面操作），不追历史（登记变更本身低频，如需审计后续加表）；
- 风险②：manifest 大域体积——P1 域规模小（法律域 KU 数十到数百），不设分页；「分页/流式拉取」记后续按需；
- 风险③：PyYAML 新依赖进内核 import 链——yaml 序列化放 **web 路由层**（`distribution.py` routes 内），内核 `distribution.py` 只产 dict+json digest，内核保持零新依赖。
