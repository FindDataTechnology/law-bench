# 三域冒烟记录（task 7.1，2026-11-03）

`tests/test_three_domain_smoke.py` 3 passed（每条 push 由 CI 复跑，此处留一次人工核读的实跑快照）：

- **法律 packs/legal**（组装→评测→复核全链）：真实条款库 `upsert_clause` 落两条 base 条款（当事人/违约责任）→ `generate_contract_assembled("sale", markdown)` 组装（断言 body 含 base-marker 与违约责任）→ `evaluate_contract`（FakeJudge，hermetic）→ `store_result` → `create_batch(validity, 双盲 2 槽)` → 逐槽 `decide_task` → `batch_stats` 复核全 decided+全 positive。
  - 口径说明：组装用的是最小合成条款（同 `tests/test_clauses_assemble.py` 的验证模式），非仓内 43 型真种子全量——真种子的 `load_one` 依赖 app 启动时把 tag_dims 灌进进程内 `TAG_VOCAB`，一次性脚本不刷新该内存表，属生产管道细节，组装**代码路径**本身是真跑的。
- **金融 packs/finance-data**（数据通道）：`load_sentiment_gold` 真读 gold-v9（幂等双跑同条数）→ `run_data_eval` kind=fact 落 `channel='data'`/`unit_kind='fact'`、n_criteria=条数×checker 数 → `build_data_qa_goldset` 每题判定函数在 `JUDGE_FUNCS` 内且对入库单元可执行通过。
- **政务 packs/gov**（数据通道）：`load_gov_registry` 真读 registry（幂等）→ `run_data_eval` kind=gov-fact 落库，`all_pass=1`（真 registry 诚实过全部确定性检查）。

判官通道（文本评测腿）在冒烟里用 FakeJudge 保持零网络零算力；真判官活体校准在 4.1（`scripts/calibrate_judge_live.py`，deepseek-v4.1-flash 一致率 60.2%），其 gold 线决策按用户意见后置。
