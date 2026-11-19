# 提案：判官置信通道选型与分层校准门（4.1 收口路径）

## Why

`add-judge-misread-remediation` 收口留下两项如实挂账的差距，且都被 run 8（2026-11-06，108 对 live 校准）的数据钉死为**链路级问题、非 prompt 迭代可修**：

1. **置信自报通道系统性失效**：105/108 输出根本不含 CONFIDENCE token（非格式/位置变体——无 token 可解析），prompt 层遵从率 ≈3%（3/108）且同款 prompt 同款端点两次复现（11-03 与 run 8）。根因在 GEval→deepeval 的输出模板吞掉自定义尾标要求：flash 级模型在该链上产出不了可校准的自报置信。现有校准门（confidence 分桶 + 单调性）因此整体失能——106/108 落 no-confidence 桶，单调性空转通过。
2. **判定本身与 gold 存在系统性偏差**：run 8 混淆矩阵 human_pass=94/judge_pass=51，42/108 是「human 判过、judge 判不过」的假阴性，human=false 的 14 对 judge 全判 fail（specificity=1.0、sensitivity≈0.55）。全量 agree 0.602 的主要成分是判官过严，而非置信缺失；类不平衡 gold（94/14）下全局 agree 率会掩盖退化解（比如全 fail 的判官 agree=14/108 但 specificity 完美）。

判官可信度是评测生态地基（meta-eval 校准、gold 信号闸、双通道评测全部以判官产出为输入）。11-03 的 4 模型校准发现是现成基线；本 change 把「置信从哪来」与「校准门怎么判」从自报 token 迁移到不依赖模型自觉的通道，并让校准门对类不平衡免疫。

## What Changes

- **采样一致率置信通道（首选实现）**：同一判分调用独立重复 k 次（温度>0），confidence = 多数票占比——不依赖任何模型自觉输出 token，任意 OpenAI 兼容端点可用；`calibrate_judge_live.py` 增 `--samples`，记录 `confidence_source="vote_share"`。判分主链（`evaluate_contract`）不动。
- **通道留痕与显式降级纪律**：校准记录带 `confidence_source` 字段；通道不可用（如 logprob 端点不支持）必须显式报无效，禁止静默回落自报 token。
- **分层校准门（换尺不换阈值）**：校准报告从「全局 agree + 自报置信分桶单调」改为 **human_pass 分层矩阵**（TP/FP/FN/TN、sensitivity/specificity、balanced accuracy、Cohen's kappa）+ 采样一致率分桶单调；`CALIBRATION_MIN_AGREE=0.70`（用户既裁）改读 balanced accuracy。旧字段（agree_rate/单调性）保留为诊断，不再作门。
- **判官通道选型对照（bake-off）**：同一 gold 集（108 对固定）对 ≥2 候选通道/模型组合各跑一轮，结果（n 调用、分层矩阵、无效率、成本）落 eval_runs meta 留痕；选型结论写回 design.md 附录。**选型不自动改生产判官**——`EVAL_MODEL` 切换是运维显式动作。
- **非目标**：prompt 措辞再迭代（已被两轮数据证伪）、gold 标签重标、GEval 框架替换、多判官集成改造（`evaluate_with_multi_judge` 现状保留）。

## Capabilities

### New Capabilities

- `judge-channel-selection`: 判官置信通道选型——采样一致率通道、通道留痕与降级纪律、分层校准门、bake-off 对照与留痕

### Modified Capabilities

（无——`judge-reliability` 尚在 `add-judge-misread-remediation` 未归档 delta 中，为避免撞车本 change 不碰它；归档时序上 `add-judge-misread-remediation` 先行。）

## Impact

- **代码**：`scripts/calibrate_judge_live.py`（采样通道+对照跑）、`src/bench/calibration.py`（分层矩阵+新门，旧字段保兼容）、校准报告落库路径。评分主链 `src/eval/scoring.py` 零改动。
- **数据**：eval_runs meta 新增 bake-off 轮次记录；零 schema 变更（records 走既有 JSONB）。
- **成本**：采样通道一轮 = 108 对 × k 次（k=5 约 540 调用，relay 实测 108 调用零错误、吞吐可承受）；bake-off 至少 2 轮。
- **风险**：k 次采样一致率可能整体偏高（判官过严是系统性的，重复采样不稀释偏置）——分层矩阵恰好独立暴露该偏置，两把尺互补；若无任何通道过门，4.1 维持不勾、差距如实记录（不造绿，沿既有纪律）。
