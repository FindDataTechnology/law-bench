## 1. 槽位名普查与值库

- [x] 1.1 对仓库快照 `contract_artifacts` 做 distinct 槽位名普查（区分显式名/类别长尾），输出普查结果确定值库覆盖面
- [x] 1.2 新建 `scripts/finetune/slot_value_bank.py`：显式槽位值表（每名 ≥8 个真实感变体）+ 类别兜底表（当事人/日期/金额/比例/期限/地点/义务/方式…）+ 缺值判定函数；纯标准库
- [x] 1.3 在 `slot_value_bank.py` 内加入合同类型 zh 名静态映射（从 `src/contracts` 模板注册表一次性提取，66 类型）与 stance 中文措辞（pro_a/pro_b/balanced）
- [x] 1.4 值库单元测试：覆盖普查全集零缺值（或缺口全部有计数）、确定性（同正文两次取值逐字节相同）、同槽位多名下不同正文取值分布非单点

## 2. 导出器双源改造

- [x] 2.1 `common.py`：占位符正则统一为 CJK+ASCII 兼容（`\w`），`export_dataset.py` 与校验共用单点定义
- [x] 2.2 `export_dataset.py`：`_build_silver_pairs()` 升级为组内择优（score_ratio 最高 → all_pass → created_at），provenance 增 `score_ratio`/`all_pass` 字段
- [x] 2.3 `export_dataset.py`：新增 `_build_synth_pairs()` 消费 `contract_artifacts`（跳过 superseded、值库实例化、task_desc 合成、`synthetic_slots: true`、缺值整行丢弃计数）
- [x] 2.4 `export_dataset.py`：drafter-a 子命令合并双源、跨源正文哈希去重（草稿源优先）、按源输出去重审计（去重前/后计数 + 丢弃计数）
- [x] 2.5 `export_dataset.py validate drafter-a`：确认 `validate_pair` 用新正则拒绝 CJK 残留占位符，合成配对通过校验

## 3. SFT 导出升级

- [x] 3.1 `export_sft_dataset.py`：drafter-a 切分改为 stance 分组分层（组内 ceil(n×val_frac)、至少 1 条当 n≥2、跨组种子 `(SPLIT_SEED, stance)` 派生），judge-c 切分不动
- [x] 3.2 `export_sft_dataset.py`：`_meta` 增 `source`（pipeline_runs/contract_artifacts）与 `synthetic_slots` 字段
- [x] 3.3 `export_sft_dataset.py`：manifest `drafter_a` 段增 `source_breakdown`、`synthetic_count`、`score_ratio_bands`

## 4. 重导出与验证

- [x] 4.1 运行 `export_dataset.py drafter-a` 重导出银牌池，核对：总量 ~520、各源计数与审计数自洽、stance/类型分布符合快照统计
- [x] 4.2 运行 `export_sft_dataset.py all` + `inspect_sft_lengths.py`，核对分层切分（每立场 val 非全落一侧）、manifest 新字段、长度分布无超长异常（Qwen 27B 上下文预算内）
- [x] 4.3 端到端回归：`export_dataset.py validate drafter-a --file ...` 全量通过；`export_dataset.py gate` 仍通过（飞轮闸门不受影响）
- [x] 4.4 新增 `tests/test_finetune_expand_drafter.py`：合成实例化（占位符清零、值如实对应、superseded 跳过、缺值丢弃、确定性重跑）、择优去重、跨源去重、分层切分复现性；`uv run --no-project pytest` 可跑（不依赖项目 venv）

## 5. 收尾

- [x] 5.1 核对 `data/finetune/sft/manifest.json` 入库内容完整（jsonl 按惯例 gitignore）
- [x] 5.2 更新变更内文档：如 README/脚本 docstring 中「548 warmup」等过期计数描述同步修正
