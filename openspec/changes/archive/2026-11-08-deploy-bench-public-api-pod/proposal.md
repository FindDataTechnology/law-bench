# Proposal: deploy-bench-public-api-pod

## Why

`public-api-service` 的实现（`create_public_app()`）与 spec 均已归档，但**公共 API pod 从未部署**——本次为 `add-bench-public-overview-tier` 做生产实证时侦察确认：cheap 集群无 `law-bench-public` deployment，`deploy/public/deployment.yaml` 镜像还停在退役的 `harbor.local/...:sha-2e6de71`，`docs/public-api-deploy.md` 的 China replica 数据链从未搭建。下游 `add-bench-chain-website` 的门 B 活水合因此挂账（站点已按诚实报因态上产：https://bench.finddatatech.cloud）。本 change 补上这个部署账。

## What Changes

- 在 cheap 集群 `law-bench` namespace 部署 `law-bench-public` deployment（镜像同 origin：`ccr.ccs.tencentyun.com/law-bench/law-template:sha-<current>`，`PUBLIC_API=1`、`READONLY_REPLICA=1`、`RATE_LIMIT_ENABLED=1`）。
- 数据链裁决落地：按 spec 要求搭 China-local Postgres read-replica（logical replication：origin `CREATE PUBLICATION` 覆盖 clauses/contract_artifacts/rubrics/criteria/prompts/tag_dims/api_keys；replica `CREATE SUBSCRIPTION`）+ China-local MinIO 镜像同步；凭据独立 `law-bench-public` SecretRef（与 origin secrets 分离）。
- Service：**新 NodePort**（不复用 30820；保持两 pod 可独立寻址），cheap1 Caddy 加 `bench-api.finddatatech.cloud`（或复用 bench 站代理后端切换）反代。
- 上线门：`/healthz` + 匿名 `GET /api/public/overview` 真值（载荷与 origin 发布状态对账）+ 限流 429 负例。
- **spec 漂移记档**：origin 已迁 cheap-8（China fleet），`public-api-service` spec 中「origin across the border」的表述与现状不符（origin 与 replica 同集群），需在 replica 就位后按事实修订该 spec 的跨境表述。

## Capabilities

### New Capabilities

- `public-api-deployment`: 公共 API pod 的部署与验收——清单、数据链、端口纪律、上线门。

### Modified Capabilities

<!-- 无：public-api-service 的行为需求不变，本 change 只补部署；跨境表述修订随 replica 就位后另记 -->

## Impact

- `deploy/public/deployment.yaml` / `service.yaml`（镜像与端口现值化）、cheap1 Caddyfile。
- origin Postgres：`CREATE PUBLICATION`；China replica：新 Postgres 实例 + subscription。
- cheap 集群配额与磁盘（2026-11-07 已回收到 66%）。
- 下游：`add-bench-chain-website` tasks 4.5 真值验收解除挂账。
