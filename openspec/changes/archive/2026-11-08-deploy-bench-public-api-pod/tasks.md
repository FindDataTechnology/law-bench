# Tasks: deploy-bench-public-api-pod

## 1. 数据链

- [x] 1.1 replica 实例就位（cheap 集群内，Postgres 14+，独立 PVC/凭据）
- [x] 1.2 数据链=快照轨：cron `pg_dump --clean --if-exists`（15min，Job 失败留痕）覆盖七表，行数对账（api_keys 承重）
- [x] 1.3 MinIO 面：origin MinIO 实况已死（svc 不存在，下载路径先于本 change 即断）→ windows 数据机 RustFS 直接作为公共读面真源（MINIO_PUBLIC_HOST=100.64.0.5:9000 + RustFS 凭据），canary 往返实弹通过；镜像 cron 退掉（无真源可镜像）
- [x] 1.4 `law-bench-public` SecretRef 注入（DSN/`AUTH_SESSION_SECRET`/China MinIO 凭据，独立于 origin）

## 2. 部署

- [x] 2.1 `deploy/public/deployment.yaml` 现值化：ccr 镜像 tag、`PUBLIC_API=1`/`READONLY_REPLICA=1`/`RATE_LIMIT_ENABLED=1`、无 seed-db/无 PVC
- [x] 2.2 `deploy/public/service.yaml` 新 NodePort（不复用 30820）
- [x] 2.3 部署滚成 + healthz 200

## 3. 出口（显式路径形态——spec「独立域名或显式路径」二选一取后者）

- [x] 3.1 bench 站 Caddy 同源代理 `/api/public/overview` 后端切新 NodePort（免第二域名 DNS/雷池/证书全套）
- [x] 3.2 独立域名（bench-api）留档为后续机器消费面选项，不在本 change —— **本条即留档本身**（同源代理已覆盖需求，见 3.1）；将来要机器消费面时另立 change

## 4. 上线门（evidence 落档）

- [x] 4.1 healthz 200
- [x] 4.2 匿名 `GET /api/public/overview` 200，载荷 digest 与分发面发布状态对账
- [x] 4.3 匿名 sibling 401 + 限流 429 负例
- [x] 4.4 evidence 样本落 `evidence/`（响应样本 + 负例）
- [x] 4.5 bench 站同源代理后端切至新端口 → 站点真值验收（水合逐字段一致）
- [x] 4.6 `openspec validate deploy-bench-public-api-pod --strict` 过绿
