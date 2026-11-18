# Public API pod 上线门 evidence（2026-11-07）
镜像 ccr law-template:sha-b1d8a66（同 origin）；PUBLIC_API=1/READONLY_REPLICA=1/RATE_LIMIT_ENABLED=1。
数据链=快照轨：law-bench-public-replica + 15min pg_dump cron（seed api_keys=14, ontology_publications=1）。
- gate1 healthz: 200 {"status":"ok"}
- gate2 匿名概览: 200，legal v1 digest 3586552a01b0…（与分发面 C3 发布对账一致），as_of=2026-11-06T03:25:44+00:00（数据时间非时钟）
- gate3 匿名 sibling: /api/public/overview/x、/api/contracts/sale、/samples 全 401（豁免精确路径不蔓延）
- gate4 限流: in-pod burst 耗尽 → 429（见 gate4_ratelimit_inpod.txt）
四门全过。出口=NodePort 30620；bench 站同源代理已切此端口。
