## Why

bench-platform（知验台，2026-11-03 归档）留了四条 deferred 腿，全部卡在「生产凭据缺失 + wire 契约缺口」上：5.1 真拉（wire 实体面只收 console Logto ID token，唯一造号脚本写生产 Logto 库=明令禁止）、5.2 真实升格抽样（随 5.1）、5.3 真回写 e2e（wire 无 tier/sensitivity 一等字段、关系无更新面——连接器如实拒绝）、6.2 市场发布门 live 双跑（原逻辑与内核 NOT EQUIVALENT，6 例对比已贴，须对生产 paas registry 补跑）。姊妹 change `add-entity-bench-contract`（fd-wire 根）落地契约修复后，这四条腿具备收账条件；操作员 console 会话（IAB 缓存 idToken 配方 10-31 实证）让首轮真跑无需等任何新通道。

## What Changes

- 连接器凭据双模：现役 `WIRE_ID_TOKEN`（操作员 console 会话）之外增 `X-Internal-Token` 机器模式（env 客户 scope 配置），按端点自动择路——读面优先机器通道（可用时），写面恒走 console 身份。凭据只经 env 注入，永不落仓。
- 真拉收账（5.1 deferred 腿）：对 drillcust001 真实本体跑 `sync_now()`，身份键与 wire 全等 + 重复同步幂等零新增，证据留档。
- 真实升格抽样（5.2 deferred 腿）：真实 wire 实体抽样走 bronze→silver→gold 全流程，审核人留痕可查。
- 真回写 e2e（5.3 deferred 腿）：实体经一等 `tier`/`sensitivity` 字段、关系经新更新面回写；成功路径拿回执、失败路径（网络断/422 漂移）知验台侧状态如实不误标。
- 6.2 市场发布门 live 双跑收账：对生产 paas registry 真实条目双跑原逻辑 vs 内核 fail-closed，裁决 NOT EQUIVALENT 问题（收敛或确认分歧并记录决策），harness 住内部仓（凭据边界）。
- 连接器契约对齐：writeback 切一等字段/更新面后，README 契约缺口清单 1/2 销账、`WireWriteback` 对 kind=relation 的拒绝路径改为真回写。

## Capabilities

### New Capabilities

- `wire-integration`: 知验台↔柏讯真实数据循环的内部连接器契约——凭据双模择路（机器读/console 写）、真实同步幂等、升格与回写的真实性判据与如实失败纪律、发布门 live 双跑裁决流程。

### Modified Capabilities

（无——本仓无既有 spec 能力被改；bench-platform spec 属 law-bench 公共仓，本 change 只兑现其 deferred 腿，不改其需求面。）

## Impact

- **代码**：`wire-connector/src/wire_connector/`（client/sync/writeback）、新增 live 双跑 harness（scripts 或 wire-connector 内）、`wire-connector/README.md` 契约缺口清单销账。
- **外部依赖**：fd-wire `add-entity-bench-contract` 上产（一等字段+更新面+机器通道）；paas 生产 registry 读面（live 双跑）；生产 Logto console 会话（操作员人工注入）。
- **凭据边界**：所有 token/DSN 经 env 注入、本仓零凭据文件（延续 CI 泄露扫描纪律）。
- **生产写入面**：回写是对 wire 生产实体的真实写——经提案纪律（只写 bench 已升格 gold 且带审核人留痕的单元），不触碰 wire 无关数据。
