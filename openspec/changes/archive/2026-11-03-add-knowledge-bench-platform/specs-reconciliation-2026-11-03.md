# 7.2 Specs 对账记录（2026-11-03）

`specs/bench-platform/spec.md` 七条 Requirement × Scenario → 已完成任务 → 盘上证据。
口径：每条 Scenario 找「已完成任务 + 测试/工件」；无证据支撑的宣称视为未交付并如实标注。

## 1. 知识单元类型化
- S1 新增 kind 不改内核 → 2.1/2.2：`src/bench/store.py`（kind 为列非分支），`tests/test_bench_store.py` 用 indicator/qa-pair 新 kind 全链往返 ✓
- S2 法律垂类零回归 → 1.4 基线 849 → 全程 937/1030/1046/1095/1145 单调加测、零 FAILED ✓

## 2. 域包插拔接口
- S1 新域包接入不触 src/bench → 2.2/2.3 + 4.4/4.5/6.1/6.2：五包（legal/gov/finance-data/text-retrieval/kg-gate）仅 pack.yaml+包内件，`tests/test_bench_packs.py` ✓
- S2 内核领域无关 → 2.4：`tests/test_kernel_domain_free.py`+`scripts/check_kernel_domain_free.py`（禁词零命中+禁 import packs，负验证钉过）✓

## 3. 双通道评测
- S1 数据对象确定性评测 → 2.5：`src/bench/data_checks.py`（永不调 judge，限流注入不污染），finance 735 criteria/gov 88 全 PASS ✓
- S2 数据 QA 金集评 AI 用数 → 4.5：goldset 10 题判定函数可执行 ✓
- S3 通道如实标注 → eval_runs.channel（text/data/meta），三处测试断言 ✓

## 4. 溯源四层与真值守卫
- S1 拒绝 bronze → tiers.py 单点守卫 + 2.6 全平台导出面，`tests/test_bench_tiers.py`/flywheel「先整池校验后写文件」✓
- S2 分层互斥 → tier CHECK + filter_by_tier；common.py re-export 到 tiers 的 object-identity 测证 ✓

## 5. meta-eval
- S1 judge 校准运行 → 4.2 `src/bench/calibration.py`+`scripts/calibrate_judge_live.py`；**活体已跑**（产库 108 金对，deepseek-v4.1-flash 60.2%、单调过，落库 run id 2）✓
- S2 未校准判官受限 → 4.3 `require_calibrated_gold_judge` 拒路径测；packs/legal 如实不声明 gold_judge ✓
- ⚠ 后置（用户 11-03 决策）：判官 80% gold 线未达+指令自报率低——词元 lane 可服务判官面不足，「绑更强上游/阈值政策」待拍板；漂移调度已就位（6.3）。

## 6. 柏讯实体升格契约
- S1 实体升格入库（身份键与 wire 一致、零第二份）→ 5.1/5.2 `src/bench/promotion.py`（external_key=源 id、双跑零写、gold 必带 session 身份 reviewer）✓（hermetic 测；真实实体抽样随 C 后置）
- S2 gold 回写带档如实失败 → 5.3 `run_writeback`（失败不误标、幂等跳过）测 ✓
- ⚠ 后置（如实）：真机拉取=deferred（graph 端点 401 可达但无生产 console 令牌，造令牌=写生产库被禁）；wire 契约缺口（实体无 tier/sensitivity 一等字段、关系无 PUT）已记两份 README，属柏讯线需求。

## 7. 开源切分边界
- S1 泄露扫描拦截 → 3.2 `scripts/check_public_hygiene.py` 进 GH Actions+Jenkins 首步；负验证钉过（植红点名→还原）；donor 白名单零凭据入仓 ✓
- S2 公共面宣称一致 → 3.3 README 对齐开源面+内部仓指路 ✓；3.1 内部仓 wire-connector 真实端点+缺口文档 ✓

## 未勾任务一览（原因均已注记）
- 4.1（活体校准全过 80% 线）：机器已跑通，判官供给未达线——用户决策后置。
- 5.1/5.4 的真实抽样腿、6.2 发布门 live 两腿：依赖外部凭据/registry，deferred 不造假。

结论：七条 Requirement 的机制面全部有「任务+测试+工件」在案；三处 deferred 皆为外部凭据/用户决策所致、非实现缺漏，且全部在 tasks.md/README/本记录显式标注——无「实现了却没勾」、亦无「勾了但没做」。
