# wire-connector（内部连接器，P2 组5「柏讯贯通」）

柏讯（fd-wire）↔ 知验台 的内部连接器。**只住内部仓**：涉及客户数据集绑定关系与内部语料，永不进公共仓。

依赖方向：内部 → 公共（VAAS 先例 `fd-coding-law-bench-mcp`：以 `LAW_BENCH_REPO`
env + sys.path 引公共仓内核 `src.bench.promotion`；law-bench **绝不**反向 import
本包）。fd-wire 对本连接器只暴露 HTTP API（兄弟仓，只读，零改动）。

## 实查到的 wire API（2026-11-03，fd-wire 盘上源码为真源）

源码位置：`fd-wire/api/fd_wire_api/entities/routes.py`（路由与 schema）、
`fd-wire/api/fd_wire_api/console/auth.py`（鉴权）、
`fd-wire/openspec/specs/entity-layer/spec.md`（契约）。

| 面 | 端点 | 鉴权 | 载荷 |
|---|---|---|---|
| 图谱读 | `GET /api/v1/entities/graph` | console Bearer ID token | `{"nodes":[GraphNodeOut], "edges":[GraphEdgeOut]}`；空图谱 200 空集 |
| 实体读 | `GET /api/v1/entities` | 同上 | `{"entities":[EntityOut]}`（信封列表） |
| 实体写 | `PUT /api/v1/entities/{id}` | 同上（actor 三元组） | **整量替换** `EntityCreateIn`：`{name, dataset_id, pk_columns, description, display_column, column_notes}`；404/409/422 语义见源码注释 |
| 关系写 | `POST/DELETE /api/v1/entities/{id}/relationships[/{rid}]` | 同上 | 声明/删除——**无更新面** |

节点形状（GraphNodeOut）：`id:int / name / description / pk_columns:[str] /
display_column / column_notes:{col:note} / dataset:{id,key,name,row_count,
storage_tier}`。边形状（GraphEdgeOut）：`id / from_entity_id / from_column /
to_entity_id / to_column / kind / label / junction_*`（m:n 三键）。

### 鉴权事实

- 身份 = **Logto ID token**，`Authorization: Bearer <id_token>`；服务端本地
  校验 JWKS/iss/aud/exp/iat（ES384/RS256/ES256），`sub → Customer` 映射。
- **实体路由上没有 machine token 旁路**（`fd_wire_internal_token` 不在此面）：
  无/坏 bearer → 401；服务端缺 `FD_WIRE_LOGTO_ISSUER/CLIENT_ID` → 503 报精确
  缺项。拿 token 的唯一路 = console 登录流（Logto SPA，scopes
  `openid profile email roles offline_access`），本连接器**不实现 OIDC 流**，
  由调用方注入 `WIRE_ID_TOKEN` env。
- 服务地址：生产前门 `https://wire.finddatatech.cloud`（cheap-1 Caddy 把
  `/api/` 反代到 tailscale mesh 上的 API NodePort **31883**，见
  `fd-wire/deploy/k8s/fd-wire-api.yaml` 注释与 `deploy/README.md`）。
  mesh 内直连可用 `http://<node-ip>:31883`。

## 配置（env）

```
WIRE_API_BASE           默认建议 https://wire.finddatatech.cloud
WIRE_ID_TOKEN           console Logto ID token（写面恒走此凭据——审核人归因在场；
                        缺失 → 客户端报错如实，不触网）
WIRE_INTERNAL_TOKEN     机器通道令牌（与 wire FD_WIRE_INTERNAL_TOKEN 同源；
                        只读镜像面）
WIRE_CUSTOMER_ID        机器通道客户键（须在 wire scope 白名单
                        FD_WIRE_INTERNAL_ENTITY_CUSTOMERS 内，越界 404）
LAW_BENCH_REPO          公共仓 checkout 路径（缺省取 sibling ../law-bench）
BENCH_DATABASE_URL（或 database_url） 知验台 Postgres DSN
```

**凭据双模择路**（close-wire-real-loop design D1）：读面机器凭据（token+客户键
齐备）即走 `/api/v1/internal/entities` 只读镜像，否则回落 console；写面无论
凭据为何恒走 console 身份。repr/错误信息永不携带令牌明文（1.4 脱敏纪律）。

## 契约缺口清单（2026-11-05 更新：1/2 已由 wire add-entity-bench-contract 0050 解决）

1. ~~wire 实体 API 无 `tier`/`sensitivity` 可写字段~~ **已解决**：一等字段
   上线（0050），连接器 `update_entity` 直写 `tier`/`sensitivity`；袋 stamp
   仍随写（承载 reviewer/idempotency 溯源，pre-0050 消费方兼容）。
2. ~~关系无任何更新面~~ **已解决**：`PUT /api/v1/entities/{id}/relationships/
   {rid}`（label/tier/sensitivity 三键必传、显式 null=清空、结构键 422）。
   `WireWriteback` 对 kind=relation 走更新面——「删除+重声明」与拒绝路径退役。
3. **PUT 是整量替换且全链重校验**（主键列 ⊆ 数据集列快照等）：若 wire 端数据集
   已漂移（列删了/实体被改名），知验台 gold 的镜像快照 PUT 回去会 422。连接器
   如实抛错（单元保持未回写 + 错误入库），由操作员先重同步再回写。
4. 回写幂等 = wire 实体键（内核 provenance 记 `writeback_idempotency_key`，
   重复 `run_writeback` 默认跳过已回写单元，不产生第二次推送）。wire 侧若有
   `If-Match`/版本头可进一步升级为服务端幂等（当前无）。
3. **PUT 是整量替换且全链重校验**（主键列 ⊆ 数据集列快照等）：若 wire 端数据集
   已漂移（列删了/实体被改名），知验台 gold 的镜像快照 PUT 回去会 422。连接器
   如实抛错（单元保持未回写 + 错误入库），由操作员先重同步再回写。
4. 回写幂等 = wire 实体键（内核 provenance 记 `writeback_idempotency_key`，
   重复 `run_writeback` 默认跳过已回写单元，不产生第二次推送）。wire 侧若有
   `If-Match`/版本头可进一步升级为服务端幂等（当前无）。

## 命令面：跑一次真实同步

```bash
cd <workspace>/law-bench-internal
export WIRE_API_BASE=https://wire.finddatatech.cloud
export WIRE_ID_TOKEN='<console 登录后从会话取的 Logto ID token>'
export BENCH_DATABASE_URL='postgresql://…(知验台库)'
PYTHONPATH=wire-connector/src python3 - <<'EOF'
from wire_connector.sync import sync_now
print(sync_now())   # {"created": [...], "updated": [...], "unchanged": [...]}
EOF
# gold 回写——操作员确认门（dry_run 先看批次；交互 y/N；脚本化用 confirm=）
PYTHONPATH=wire-connector/src python3 - <<'EOF'
from wire_connector.sync import bench_connect
from wire_connector.writeback import run_writeback_confirmed
conn = bench_connect()
print(run_writeback_confirmed(conn, "wire", dry_run=True))    # 只预览零写
print(run_writeback_confirmed(conn, "wire"))                  # 交互确认后推
print(run_writeback_confirmed(conn, "wire", confirm=lambda b: True))  # 脚本 --yes
EOF
```

离线自检（不触网，stdlib 直跑）：`python3 wire-connector/selfcheck.py`。

## 实跑证据（C 真机冒烟，2026-11-03）

### 探测记录（只读 GET，无任何生产写）

| 目标 | 结果 |
|---|---|
| `https://wire.finddatatech.cloud/api/v1/entities/graph` | **HTTP 401**，body 逐字 = `{"detail":"缺少 Bearer ID token（控制台鉴权）"}` —— 与 `console/auth.py:152` 的 401 文案一致，证明请求**穿过 Caddy 抵达 fd-wire api 本体**（不是代理层的 404/502） |
| mesh 直连 `http://100.64.0.12:31883`（china-cheap-3） | HTTP 401 |
| mesh 直连 `http://100.64.0.8:31883` / `100.64.0.9:31883`（cheap4/5） | HTTP 401 |
| mesh `http://100.64.0.11:31883`（china-cheap-1） | 不通（该节点非 k8s 成员，Caddy 机） |

**API 可达、身份门工作正常。** 但实体面鉴权只有 console Logto ID token（无
machine 旁路，见上「鉴权事实」），本机 tailscale 在线、凭据线索排查了
`law-bench-server/.env`（**该目录已于 2026-11-08 归档到 `attic/law-bench-server-2026-11-08.tar.gz` 并删除**；当时只有知验台自身 Logto 配置）、`fd-wire/deploy`、
`fd-infra-deploy`——均无可用的 wire console 用户令牌；唯一造 token 的路径是
`fd-wire/scripts/provision_service_account.py` 往**生产 Logto 用户库插账号**
（兄弟仓生产写，明令禁止，且新账号客户域内实体为空图谱，也换不来本体舰队的
真实数据）。

**结论：真拉 deferred** —— 可达但无凭据。A 的 hermetic 链 + 下方本地真库
贯通冒烟作为本轮验收；持有 console 会话的操作员按「命令面」一节即可补跑
真实图谱拉取。

### 本地真库贯通冒烟（connector → kernel → 本地 PG，fixture 数据标注清楚）

`uv run python`（law-bench venv 的 psycopg）+ `PYTHONPATH=wire-connector/src`，
对一次性库 `wire_connector_smoke` 跑全链（数据为 fixture 示例实体 101/102/109，
**非** wire 真实行）：

```
SYNC1 {'nodes': 2, 'edges': 1, 'created': ['101','102','109'], ...}
SYNC2 idempotent {'created': [], 'updated': [], 'unchanged': ['101','102','109']}
GOLD payload: {... 'external_key': '101', 'tier': 'gold', 'sensitivity': 'internal',
               'review': {'reviewer': 'local-smoke-operator', ...}, 'written_back': False}
WRITEBACK {'succeeded': 0, 'failed': 1, 'skipped': 0}
  failed[0].error: no wire API base configured: set WIRE_API_BASE (e.g. https://wire.finddatatech.cloud) or pass base_url=...
unit written_back: False | tier: gold
SMOKE DONE
```

要点：跨仓 import（internal→public）在真实 Postgres 上跑通；双跑同步幂等；
gold 载荷带身份键+tier/sensitivity；真实 `WireWriteback` 通道在无凭据环境下
**如实失败**——单元未被误标「已回写」（`written_back: False`），tier 保持
gold。

### 离线自检输出（`python3 wire-connector/selfcheck.py`）

```
OK 1 wire_connector imports (client/sync/writeback)
OK 2 public kernel promotion module: .../law-bench/src/bench/promotion.py
OK 3 wire-shaped node/edge render into unit bodies/keys
OK 4 client builds; no-cred paths raise actionable errors pre-network
OK 5 gold writeback stamp: platform=knowledge-bench; tier=gold; sensitivity=confidential; ...
ALL SELFCHECKS PASSED (offline; no network touched)
```

