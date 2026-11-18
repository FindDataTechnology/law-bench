# public-api-deployment Specification（delta）

## Purpose

把已实现未部署的公共 API pod（`create_public_app()`）落成生产实体：清单、数据链、端口纪律与上线门。与 origin 同镜像、不同环境变量选择不同 app 工厂。

## ADDED Requirements

### Requirement: 公共 pod 部署形态

cheap 集群 `law-bench` namespace SHALL 运行 `law-bench-public` deployment：镜像与 origin 同源（ccr `law-template:sha-<current>`），环境 SHALL 含 `PUBLIC_API=1`（选择 `create_public_app()`）、`READONLY_REPLICA=1`、`RATE_LIMIT_ENABLED=1`；凭据 SHALL 走独立的 `law-bench-public` SecretRef（`database_url`/`AUTH_SESSION_SECRET`/China MinIO 凭据），SHALL NOT 复用 origin 的 secrets。公共 pod SHALL 无 `seed-db` initContainer、无 `db` PVC（数据来自 replica，非本地盘）。

#### Scenario: 同镜像双姿态

- **WHEN** 枚举 `law-bench` namespace 的 deployment 镜像与环境
- **THEN** `law-bench-public` 与 `law-bench` 镜像 tag 相同，前者 `PUBLIC_API=1` 后者无此变量

#### Scenario: 凭据分离

- **WHEN** 比对两个 deployment 的 envFrom secretRef
- **THEN** 公共 pod 使用独立的 `law-bench-public` secret，不与 origin 共享任何凭据对象

### Requirement: 数据链（replica，双轨机制）

公共 pod 的 Postgres SHALL 为 China-local read-replica，覆盖 `clauses`/`contract_artifacts`/`rubrics`/`criteria`/`prompts`/`tag_dims`/`api_keys`（`api_keys` 为验钥承重表）。数据链机制 SHALL 为双轨之一：**(a) logical replication**（origin publication + replica subscription——origin Postgres 的 `wal_level` SHALL 已为 `logical`）或 **(b) 周期快照**（cron `pg_dump`→restore，同步周期 SHALL ≤30 分钟；origin Postgres 为共享实例且改 `wal_level` 需重启时，(b) 为默认轨）。两轨同责：`api_keys` 行数 SHALL 可对账；同步 SHALL 不可用时公共 pod 按如实降级要求处理（概览端点 503 报因），SHALL NOT 回退陈旧数据冒充新鲜。China-local MinIO 镜像（语料 artifacts 下载面）SHALL 在概览门之外单独补齐，SHALL NOT 阻塞概览上线。

#### Scenario: 承重表对账

- **WHEN** 数据链同步运行后对账 origin 与 replica
- **THEN** `api_keys` 行数一致（公共 pod 可本地验钥），其余覆盖表行数一致或差量在同步滞后窗口内

#### Scenario: 停更如实

- **WHEN** 快照同步任务连续失败超过两个周期
- **THEN** 同步任务状态可观测（Job 失败留痕），公共概览端点按如实降级要求返回 503 报因，不输出旧数据

### Requirement: 端口纪律与上线门

公共 pod 的 Service SHALL 使用**新** NodePort（SHALL NOT 复用 origin 的 30820，两 pod 保持独立寻址）；Caddy 反代 SHALL 以独立域名或显式路径指向该端口。上线门 SHALL 全过才算部署完成：`/healthz` 200、匿名 `GET /api/public/overview` 200 且载荷与发布状态对账（digest 与分发面一致）、匿名 sibling 401、超限 429。部署 SHALL 记录 evidence（端点响应样本 + 限流负例）。

#### Scenario: 上线门全过

- **WHEN** 公共 pod 滚成后执行上线门清单
- **THEN** healthz/概览/sibling/限流四项全过且 evidence 落档，缺任一项不得宣告完成

#### Scenario: 独立寻址

- **WHEN** 分别请求 origin 与公共 pod 的 Service 端口
- **THEN** 两端口各自可达且返回各自 app 的姿态（origin 匿名 401/404，public 匿名概览 200）
