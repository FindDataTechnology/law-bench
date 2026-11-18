# Design: deploy-bench-public-api-pod

## Context

侦察结论（2026-11-07）：cheap 集群无 `law-bench-public`；`deploy/public/deployment.yaml` 镜像停在退役的 `harbor.local:sha-2e6de71`；`docs/public-api-deploy.md` 的 replica/MinIO 数据链未搭建。`add-bench-chain-website` 已按诚实报因态上产（https://bench.finddatatech.cloud，代理 /api/public/overview → origin 30820 预留、透传 404）。

## Decisions

### D1. 同镜像 + env 选择 app 工厂（沿 spec 既有裁决）
镜像 ccr `law-template:sha-<current>`；`PUBLIC_API=1` 让 `docker-entrypoint.sh` 选 `create_public_app()`。不做独立构建。

### D2. 数据链走快照轨（pg_dump cron），不动共享 origin Postgres
origin Postgres（ns postgres，postgres:16 STS）为共享实例（readiness 探 appdb），`wal_level=replica`——开 logical replication 须改配置重启共享生产库，爆炸半径不成比例。选文档 fallback A：cron `pg_dump`（15 分钟，`--clean --if-exists` 幂等恢复）→ replica。spec 已修 dual-track（(b) 为 origin 共享实例时的默认轨）。MinIO 镜像单独补齐不阻塞概览门。原裁决标题留档：数据链按 spec 补真 replica，不走「直连 origin 库」捷径
用户 2026-11-07 否决了「DSN 暂直连 origin 同库」的起步形态（B 裁决后又改 A），定：replica 数据链完整搭建。publication 覆盖 spec 点名七表；cheap 集群内新建 Postgres 实例（复用 cheap3 paper-trading-pg 的部署形态），订阅落位后对账。

### D3. 端口：新 NodePort（30620 段按集群空闲实选），不复用 30820
Caddy 侧以 `bench-api.finddatatech.cloud` 反代该端口（DNSPod 加记录 + 雷池并入 site 31 + 20 域证书再加 SAN——沿 bench 站先例全套）；同时把 bench 站的同源代理后端从 origin 30820 切到该端口。

### D4. 上线门四项 + evidence 落档
healthz / 概览真值 / sibling 401 / 429 负例，全过才算完成；样本落 `evidence/`。

### D5. spec 漂移修订随本 change 记录
`public-api-service` spec 的「origin across the border / cross-border」表述基于美国 origin 时代；origin 现居 cheap-8 与 replica 同集群。本 change 的 MODIFIED delta 在 replica 就位时修订该表述（不改变行为需求）。

## Risks / Trade-offs

- origin 主库建 publication 的写放大（新表列入发布）→ 七表都是小表，风险低。
- replica 滞后窗内 key 撤销不即时 → 验钥对账门覆盖。
- 新公开面（NodePort + 新域）→ 限流双层 + key-only 姿态继承 + fail-closed 豁免继承。

## Migration Plan

replica + cron 快照先行 → secret 注入 → pod 部署 → 上线门 → bench 站代理切新端口（显式路径形态，免第二域名全套）→ 真值验收解除挂账。

### D3. MinIO 裁决（2026-11-07 实况修正）：windows 数据机 RustFS 直接当真源
origin 的 `minio.minio.svc.cluster.local` 在集群内不存在（DNS rcode=3、无 svc/pod、无部署清单）——origin 自身的 artifacts 下载路径先于本 change 即已断（`_client` list 失败）。用户点名方案=用 windows 数据机（100.64.0.5）的 MinIO/RustFS。落地=公共 pod env `MINIO_PUBLIC_HOST=http://100.64.0.5:9000` + RustFS 凭据（task 5.2 的现成机制），canary 往返实弹通过；双端镜像 cron 退掉（无活真源可镜像）。origin MinIO 的重建属 public-api-service 线另案。

## Open Questions

- replica 实例落位节点（cheap3 docker vs 集群内 PVC pod）——实施时按磁盘余量实选。
