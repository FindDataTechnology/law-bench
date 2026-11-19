## Why

知验台（bench）与柏讯（wire）之间今天**没有任何一份文档说清两层本体是什么关系**，而代码已经按三种互相矛盾的假设各走各的：

- 蓝图 §六 已裁「wire 是 seed 原料源，**已发布本体的权威源是平台**」；
- `wire-integration` 的规格要求 `sync_graph` 持续幂等镜像 wire 实体 → bronze（这等于把 wire 当身份主键源）；
- wire 侧 `entities` 表又有自己的 console 编辑面、版本快照、diff 与回滚（事实上的第二权威）。

后果不是理论上的：唯一一条真跑过的发布-拉取链（legal v1，digest `3586552a`，2026-11-06）在生产上**关着**——`BENCH_PULL_ENABLED` / `BENCH_CONSUMER_TOKEN` 在 `deploy/k8s/*.yaml` 与 `fd-infra-deploy` 全部零命中；即便打开，拉下来的快照在 wire 侧**没有任何读面**（只有 `X-Internal-Token` 的内部投影，console / MCP / 前端零引用）。而 `crosswalk`（in-flight `add-crosswalk-seam`，19/22）正是为「两层之间怎么对齐」写的，却止步于 bench 库内，出不了发布面。

为什么现在做：`add-layered-ontology-templates` 刚把层做成一等属性（20/23），`add-crosswalk-seam` 刚把缝落成 KU——**两件事合起来才第一次具备「说清这条缝」的条件**。再晚，分层模板会被按「持续镜像」的旧假设接上，届时退役一套已经在跑的同步比现在写清一份契约贵得多。

## What Changes

- **两层职责写成契约**：`wire entities` 是**本地层**（客户语义，权威在客户，客户可编辑）；bench 发布的域本体是**共享层**（权威在平台，只经发布-拉取）。两层之间**只允许 crosswalk 一条边**，MUST NOT 循环镜像、MUST NOT 互写。
- **升格环退役读方向**：`sync_graph` 由「持续幂等镜像」降级为「**一次性 seed 导入**」（把 wire 已有实体导入为 bronze 候选，同一数据集重复导入幂等但仍是一次性语义，不是持续同步任务）；写方向（gold 的 `tier`/`sensitivity` 回写）**保留**——方向正确，它是「平台确认过的映射去标注客户实体」，不是反向写入本体。
- **拉来的快照要有脸**：wire 侧为已拉取快照提供**登录态只读读面**（不是 `X-Internal-Token` 的内部端点），控制台本体页可见「标准本体 · 版本 / digest / 条目数 / 拉取于」。
- **生产拉取按纪律打开**：`BENCH_PULL_ENABLED` / `BENCH_CONSUMER_TOKEN` 进 wire 的部署清单，前置条件是一次 `pull_and_store` 真跑成功——不许先开开关再验凭据。
- **对外口径收紧**：bench 门面站「柏讯以拉取客户端订阅发布面，真拉落库幂等、投影可查」改为**能力口径**（消费端接入能力已交付、生产订阅未开启），待 P1 落地再改回已上线口径。
- **不在本变更内**：crosswalk 作为可发布资产（依赖 `add-typed-publications`）、bench 建 `wire` 域并灌真实 crosswalk（依赖分层模板收口）。二者在 proposal 的「明确不做」中挂账，避免本条缝再长出第二种形状。

## Capabilities

### New Capabilities

- `bench-wire-seam`: 两层本体的职责边界与唯一连接——本地层/共享层各自的权威、crosswalk 作为唯一跨层边的位置与方向、一次性 seed 导入与持续镜像的分野、回写方向的单向性（平台确认 → 标注本地），以及「谁在什么条件下可以对外声明这条缝已接通」的判据。

### Modified Capabilities

- `bench-platform`: 柏讯实体升格契约由「持续从 wire 读取实体/关系作为 seed 升格原料」改为「**一次性 seed 导入**；持续同步不是契约要求，且 MUST NOT 把 wire 当作身份主键源」；同时显式写明已发布本体的权威源是平台（补上蓝图 §六 的契约落点，今天规格里只有方向性表述）。
- `wire-integration`: 「真实同步幂等」要求补一句时限——幂等仍是要求（重复导入零漂移），但**持续同步不是**；新增「两层职责与唯一连接」的边界断言，防止连接器再被当成常驻同步通道。

## Impact

- **规格（law-bench-internal）**：`openspec/specs/bench-platform/spec.md`、`openspec/specs/wire-integration/spec.md` 各一处 delta；新增 `openspec/specs/bench-wire-seam/spec.md`。`add-crosswalk-seam` 的 spec 增量补一条「crosswalk 是两层之间唯一连接」的边界断言（该 change 仍在途，delta 在它自己的目录内）。
- **代码（law-bench-internal）**：`src/bench/promotion.py` 的 `sync_graph` 文档与调用点语义收窄（代码可零改动，改的是契约与误解）；`wire-connector/README.md` 的「命令面」明确写一次性。
- **代码（fd-wire，跨仓）**：`api/fd_wire_api/bench_pull/` 增加登录态只读路由（复用 console 鉴权，不改 0052 两表）；`web/src/console/` 本体页新增只读区；`deploy/k8s/fd-wire-api.yaml` 增加 `BENCH_PULL_URL` / `BENCH_PULL_ENABLED` / `BENCH_PULL_DOMAINS` 字面值与 `BENCH_CONSUMER_TOKEN` secretKeyRef。
- **代码（fd-bench-web，跨仓）**：`src/pages/index.astro` 第三节点与 `PRODUCT.md` 的「③ 柏讯消费」措辞改能力口径。
- **风险**：打开生产拉取是本变更唯一有外部副作用的动作——令牌若已被吊销会每轮 403 进日志。缓解：开关前置一次真跑验证，并且在 `pull_and_store` 已把失败如实记入 `bench_pull_log` 的前提下，失败是可见的而不是静默的。
- **明确不做**：crosswalk 的发布面（待 `add-typed-publications`）；bench 建 `wire` 域与真实 crosswalk 灌入（待分层模板收口）；wire 本地版本化（0019）的任何改动。
