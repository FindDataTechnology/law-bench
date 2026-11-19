# 任务：add-judge-model-selection

## 1. 分层校准门（calibration 内核）

- [x] 1.1 `src/bench/calibration.py` 新增纯函数：confusion_matrix(records) → TP/FP/FN/TN + sensitivity/specificity/balanced_accuracy/kappa（空集/单类 gold 的边界显式处理，不抛不静默）
- [x] 1.2 校准门改判：balanced_accuracy ≥ CALIBRATION_MIN_AGREE(0.70) 且通道置信分桶单调；旧 agree_rate/自报分桶降为诊断字段；报告串含新门片段（可被 `is_calibrated` 兼容解析或同步迁移并留兼容测试）
- [x] 1.3 单测：退化解（全 fail 判官，specificity=1.0/balanced≈0.5）必须 fail；过门样例 pass；no-confidence 桶不得充当通过证据

## 2. 采样一致率通道（driver）

- [x] 2.1 `scripts/calibrate_judge_live.py` 增 `--samples k`（缺省 5，k=1 显式标记无通道）与 `--candidate <label>`：同一对独立 k 次判分（temperature>0），confidence=多数票占比，记录 `confidence_source="vote_share"` + k 次原始判定
- [x] 2.2 通道降级纪律：call_error/通道不可产出的记录显式 `confidence_source="none"`，不落伪装置信；run 落库带 candidate 标识、k、调用数、分层矩阵、无效率
- [x] 2.3 单测/干跑：mock judge 下 k 次票聚合、无效率统计、落库字段形状（沿既有 meta 通道，零 schema 变更）

## 3. bake-off 实跑与选型留痕

- [x] 3.1 候选① 采样通道实跑（**如实部分达成**）：k=5 全量轮被 relay 拖死（deepeval GEval 每次 measure 含 steps+evaluate 两次 LLM 调用、实测 13/11.6/48.8s，tenacity RetryError/TimeoutError；优化=按 guidance 缓存 evaluation_steps、单次调用异常降级 dropped、超时封顶）——**未出全量 108 对 run，不冒充完成**。改跑 8 对+20 对定界 pilot（同一固定 gold 集前 N 对、两候选同口径）：run 4（n=8，单类 gold，balanced=none、门 fail）、**run 5（n=20，agree 0.45、balanced 0.6944、kappa 0.1129、all_pass=False）**；20 条全部 confidence_source=vote_share、零调用错误、零 dropped——**采样一致率通道工程可用已实证**，但置信反直觉（18/20 conf=1.0、[0.6,0.7) acc 1.0→[0.9,1.0] acc 0.389 单调性挂）。
- [x] 3.2 候选②（glm-5.3-flash，11-03 基线中除现行判官外唯一可服务者）采样通道实跑（**如实部分达成**）：k=5 全量轮同样被 relay 超时/InternalServerError 拖死；k=3 定界 20 对 pilot **run 6**（agree 0.10、balanced 0.50、kappa 0、all_pass=False、20/20 vote_share、零错误、判官全判 fail）——与 11-03 基线（15/108）同一系统性过严。另以 11-03 存档在**新分层门**下重算：run 2（run8-flash-k1，108 对，balanced 0.7713 过门、kappa 0.2352、但 105/108 无置信→分桶单调空转）、run 3（glm53-k1，balanced 0.5053 挂）。
- [x] 3.3 对照判读（design.md 附录已写，引用 run 1-6）：**无候选通过分层门**；采样通道解决了「置信从哪来」但没解决「判官过严」（FN 偏置稳定，k 次重复只把错误票投得更一致）；分层矩阵独立暴露该偏置=两把尺互补的设计意图实证。生产 EVAL_MODEL 不动。
- [x] 3.4 `add-judge-misread-remediation` 4.1 注记联动：不过门→维持不勾，注记补「分层门+采样通道已上线（run 5/6 实证），差距=判官过严与 relay 不可用；4.1 挂账不销」

## 4. 回归与收口

- [x] 4.1 全量回归绿（**1325 passed / 60 skipped / 0 failed**，17 分钟）+ strict 绿
- [x] 4.2 评分主链隔离核查：`git diff -- src/eval/scoring.py` = 0 行（评分载荷形状零变化）
