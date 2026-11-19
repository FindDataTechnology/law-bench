# Design — close-wire-real-loop

## Context

- 连接器现状（wire-connector/README.md 钉死）：client/sync/writeback 就位、selfcheck 全过、hermetic 链+本地真库贯通冒烟已跑；真拉 deferred 于「可达但无凭据」；`WireWriteback` 对 kind=relation 抛错（wire 无更新面）；实体回写以 `column_notes["_bench"]` 袋承载档位标记。
- 依赖契约：fd-wire `add-entity-bench-contract` 交付一等字段（0050）、关系更新面、`/api/v1/internal/entities` 机器只读面（X-Internal-Token + 客户 scope 白名单）。本 change 在其上产后实施；机器通道未上产前，读面以 console 模式先行。
- 6.2 遗留：市场发布门双跑结论 NOT EQUIVALENT（registry 未 seed 真实条目时原逻辑仍放行、内核 fail-closed），6 例对比已贴 packs/kg-gate/README.md；判据脚本本体在 packs/kg-gate（离线可验）。
- 凭据事实：唯一可用读凭据=操作员 console 会话（IAB 浏览器缓存 `wire.console.session` 的 idToken，10-31 实证配方，~1h 有效）；生产 Logto 写库明令禁止。

## Goals / Non-Goals

**Goals**：四条 deferred 腿（5.1/5.2/5.3/6.2）真跑收账；连接器契约面升级到新 wire 契约；每条腿的验收证据留档可审计。

**Non-Goals**：bench-platform spec 需求面改动（属 law-bench 公共仓）；wire 侧任何改动（姊妹 change）；持续同步的调度部署（cron/Job——本轮先证通道，调度属后续运维）；judge 校准相关（独立线）。

## Decisions

**D1 凭据双模在 client 层单点实现，不做两套客户端。** `WireClient` 构造时接受可选两组凭据（`internal_token=` / `id_token=`），读面方法运行时择路（internal 可用即走），写面方法断言 id_token 在场（缺失即报错，与现役 no-cred 行为同纪律）。备选「分两个 client 类」被否：sync/writeback 调用方要感知择路细节，违反「内核载荷不变」的连接器承诺。

**D2 真拉首轮以 console 模式跑，不等机器通道上产。** 操作员会话配方实证（idToken 直取），五分钟内可跑；机器通道上线后重跑一次作为切换验收（两次同步结果一致性=通道等价的实证）。任务分两档：首轮（console）+ 切换复跑（internal）。

**D3 回写提案纪律=白名单批次。** `run_writeback` 增批次显式化：只处理「gold 且审核人留痕且未回写」单元（现役行为），本轮加「批次摘要预览 + 操作员显式确认」（交互式确认或 `--yes` 旗标），防误推生产。单元级幂等键沿用（writeback_idempotency_key）。

**D4 422 漂移处置=重同步后再回写，不自动改写 wire。** wire 数据集漂移（列删/改名）导致整量替换 PUT 422 时：如实记失败 → 提示重同步 → 重同步后镜像快照更新 → 重跑回写。不做「连接器智能合并」——镜像快照是 gold 的真实来源，静默合并会破坏「gold 可回指 wire 源声明」的溯源链。

**D5 发布门双跑 harness 住 wire-connector 旁（scripts/），凭据经 env。** harness 对生产 registry 只读（GET tool_list/metadata 面），逐条目产出 `{item, original_decision, kernel_decision, agree}` 行 + 汇总；分歧例强制人工归因字段（不可空跑过）。双跑结论与裁决写入 packs/kg-gate/README.md（公共仓无凭据，只写结论与归因——细节数值脱敏）。

**D6 证据留档统一放 `wire-connector/evidence/2026-11-05-real-loop/`**（本仓内）：同步报告、升格抽样记录、回写回执、双跑裁决。README 命令面章节更新为双模配方。

## Risks / Trade-offs

- [操作员 idToken 过期（~1h）打断长流程] → 分腿执行：同步（分钟级）→ 升格（人工核验，可离线久留）→ 回写（再取新 token）；每腿独立留证，无需全程单 token。
- [生产实体数据被误写] → D3 白名单批次+显式确认；单元级幂等；失败不重试盲推；回写仅 gold 单元（人工核验过）。
- [wire 契约变更未上产先跑连接器] → 任务依赖显式标注：5.3 腿前置=姊妹 change 出片上产（探针：实体 PUT 收 tier 字段 200 且关系 PUT 存在）。
- [live 双跑对生产 registry 的读取压力] → 只读 GET、单轮、条目级缓存本地；无写路径。

## Migration Plan

1. 连接器双模改造 + 契约面切换（hermetic 测试全绿先行）。
2. 首轮真拉（console 模式）→ 升格抽样 → （候姊妹 change 上产）真回写 e2e。
3. 机器通道上线后切换复跑（通道等价实证）。
4. 发布门 live 双跑 + 裁决记录。
5. README 契约缺口清单 1/2 销账、evidence 目录归档。

## Open Questions

（无——凭据路径、批次纪律、漂移处置均已在决策钉死；操作员会话获取属执行期人工动作。）
