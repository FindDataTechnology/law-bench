# 设计：判官置信通道选型与分层校准门

对应 `add-judge-misread-remediation` 4.1 的收口路径。前置事实全部来自 run 8（2026-11-06，108 对 live 校准，`/tmp/calib_full.json` 存档）与 11-03 校准存档。

## D1 数据事实（设计输入）

| 事实 | 数值 | 含义 |
|---|---|---|
| CONFIDENCE token 缺失 | 105/108（tail=3, mid=0, none=105） | 自报通道无信号可解析，宽容化被否决 |
| prompt 遵从率 | 3/108 ≈3%，两轮复现 | prompt 迭代路径证伪 |
| 混淆矩阵 | human=94 过/14 不过；judge=51 过/57 不过；TP=51 FN=42 TN=14 FP=0 | 判官系统性过严：specificity=1.0、sensitivity≈0.55 |
| 全局 agree | 65/108=0.602 | 主成分是 FN，不是置信缺失 |
| no-confidence 桶 | 106/108 | 旧分桶门整体失能、单调性空转 |

推论：换尺必须同时解决两件事——置信来源（通道）与门对类不平衡的免疫力（分层矩阵）。只换通道不换门，42 个 FN 仍把 agree 压在 0.6 以下且看不出偏置方向。

## D2 置信通道选型（三选一取舍）

| 通道 | 机制 | 取舍 |
|---|---|---|
| **采样一致率（选）** | 同一判分独立 k 次（temperature>0），confidence=多数票占比 | 不依赖模型自觉；任意 OpenAI 兼容端点可用；成本 k×n；已有多判官投票代码（`evaluate_with_multi_judge` 的 vote 语义）证明该信号形态在库内先例 |
| 原生 logprob/置信 | 端点返回 token 概率 | relay 链（token.finddatatech.cloud→deepseek）不保证透传 `logprobs`，GEval/deepeval 也不暴露——依赖两端都改，不可控 |
| 自报 token（弃） | prompt 尾标 | 两轮数据证伪；保留 `parse_confidence` 仅作 legacy 解析与 invalid 判定输入 |

降级纪律：通道声明了就必须产出或显式报无效；`confidence_source` 逐条留痕（`vote_share` / `none`），禁止未声明回落。

## D3 分层校准门（换尺不换阈值）

- 新增纯函数层（与既有 `bucket_accuracy`/`monotonicity` 同层）：`confusion_matrix(records)` → TP/FP/FN/TN + sensitivity/specificity/balanced_accuracy/kappa；门 = balanced_accuracy ≥ `CALIBRATION_MIN_AGREE`（0.70，用户既裁，语义从「全局 agree」迁为「类平衡 agree」）**且** 置信分桶单调（桶改用通道置信）。
- 旧字段 `agree_rate`、旧自报分桶保留为诊断输出，不参与门；`no-confidence` 桶不得充当通过证据。
- 单调容忍度沿既有 `MONOTONIC_TOLERANCE`。
- 门不通过时 run 记 fail，报告如实——沿「宁无效不假绿」纪律。

## D4 bake-off 协议与落库

- gold 集固定：`/tmp/gold_validity_pilot.json`（108 对，双标注 QC 过）不得改动，保证跨候选可比。
- 候选 = 通道 × 模型端点 组合；每候选一轮完整校准，落既有 eval_runs meta 通道，run 记录带 `candidate` 标识、k、调用数、分层矩阵、无效率、（可得时）成本。首轮至少：①现行 judge + 采样通道（k=5）；②11-03 四模型基线中表现最优者 + 采样通道（凭据可用性定，不可用则如实记录跑不动的候选）。
- 预算：540 调用/候选（108×5）；relay 实测 108 调用零错误，量级可承受；线程池并发沿 driver 既有实现。
- 选型结论以 run id 为证据写回本文件附录；生产 `EVAL_MODEL` 切换是显式运维动作，不在本 change 内执行。

## D5 风险

- **采样不稀释系统性偏置**：判官过严是判定口径问题，k 次重复只会稳定地错——分层矩阵独立暴露（sensitivity 低→门 fail），两把尺互补而非冗余。
- **k 偏大成本失控**：k 缺省 5、上限 9；k=1 等价于无置信（显式标记），不冒充通道。
- **并发/限速**：沿 driver 既有 ThreadPoolExecutor + 重试；relay 429 时退避重试，仍失败如实计入 call_error。
- **gold 泄漏风险**：gold 集不得因任何候选结果回改；发现标注错误另行走人工流程，不在校准轮内修。
- **兼容**：校准报告消费方（`is_calibrated` 解析、web 展示）读旧字段仍工作；新字段纯增量。

## 附录：bake-off 实跑记录与选型定谳（2026-11-06，apply 期）

**外部条件（如实）**：判官 relay `token.finddatatech.cloud` 在本次实跑窗口严重退化——`deepseek-v4.1-flash` 一度返回 400「积分已耗尽」（后恢复但延迟飙升），`glm-5.3-flash` 短文本可用、全量 payload 间歇 503/超时；deepeval GEval 单次 `measure` 含 evaluation_steps + evaluate 两次 LLM 调用（实测 13/11.6/48.8s），十重试封装 `tenacity` 会抛 RetryError(TimeoutError)。**k=5 全量 108 对轮（540 调用/候选）三次尝试均未跑完，无全量 run 落库——不造数据、不冒充完成**。driver 侧三项硬化（按 guidance 缓存 evaluation_steps、单次异常降级 dropped 记录、超时/重试封顶）已落地并有 14 项单测。

**落库 run（本地 dev PG，channel='meta'/unit_kind='judge'）**：

| run | 候选 | gold | n_calls | agree_rate | balanced_acc | kappa | monotonic | all_pass |
|---|---|---|---|---|---|---|---|---|
| 1 | flash-k1-credits-probe（k=1 smoke） | 前 3 对 | 3 | 0.667 | none（单类） | 0.0 | 空转 yes | False |
| 2 | run8-flash-k1（11-06 存档重算） | 全 108 | 108 | 0.602 | **0.7713** | 0.2352 | 空转 yes（105 无置信） | **True** |
| 3 | 11-03-glm53-k1（存档重算） | 全 108 | 108 | 0.139 | 0.5053 | 0.0028 | yes | False |
| 4 | flash-vote-k3-pilot（采样通道） | 前 8 对 | 24 | 0.375 | none（单类） | 0.0 | **no** | False |
| 5 | flash-vote-k3-pilot20（采样通道） | 前 20 对 | 60 | 0.450 | **0.6944** | 0.1129 | **no** | False |
| 6 | glm53-vote-k3-pilot20（采样通道） | 前 20 对 | 60 | 0.100 | 0.5000 | 0.0000 | yes | False |

**通道实证**：run 4/5/6 共 48 条记录全部 `confidence_source=vote_share`、零调用错误、零 dropped——采样一致率通道**工程可用**（对比自报通道 105/108 无 token）。置信分布反而暴露新事实：run 5 有 18/20 记录 conf=1.0（k 次重复把判官的过严偏置投得更一致），且 [0.6,0.7) 桶 acc=1.0 → [0.9,1.0] 桶 acc=0.389 单调性挂——**D5 风险①「采样不稀释系统性偏置」被实证**：采样解决了「置信从哪来」，没解决「判得准不准」；分层矩阵独立抓出该偏置（run 5 balanced 0.6944、run 6 0.50 均不过门），两把尺互补的设计意图成立。

**选型定谳**：
1. **无候选通过分层门**（run 5/6 均 all_pass=False）；run 2 虽 balanced 0.7713 过门，但它是 k=1 自报通道、105/108 无置信使分桶单调性空转，且 kappa 仅 0.2352——**不构成可校准判官的证据**（正是本 change 要替换的旧世界），不据此勾选 4.1。
2. 生产 `EVAL_MODEL` 保持 `openai/deepseek-v4.1-flash` 不动；切换是显式运维动作，选型记录不越权。
3. 解禁路径（挂账）：①绑更强/更稳定的判官上游（relay 退化是本次全量轮失败的直接原因）②判官口径与 gold 的「过严」偏差另立校准/阈值政策轮（非本 change 范围）③维持 silver-only。
4. `add-judge-misread-remediation` 4.1 维持不勾：结构性误读已堵、分层门与采样通道已上线并有 run 实证，但 all_pass 合理区间仍无候选达成，差距如实挂账。

## 附录二：出片后 relay 复盘与解禁重跑配方（2026-11-07 凌晨）

**复盘**：镜像 `sha-a41f38d` 上产后，对两个候选判官端点做 3 次全量 payload 探测——`deepseek-v4.1-flash` 三次均 40s 读超时（无 HTTP 响应）；`glm-5.3-flash` 一次 40s 超时、一次 502「Upstream service temporarily unavailable」、一次 503。**relay 退化未恢复**，全量 108 对 bake-off 仍不可跑，4.1 维持不勾、挂账不销。此前 pilot 的结论不受影响（那是 relay 短暂可用窗口内真实落库的 run 4/5/6）。

**重跑配方（relay 恢复后一键执行，不造数据）**：

```bash
cd <workspace>/law-bench-internal
export database_url="postgresql://app:change-me-please@localhost:5432/law_bench"  # 本地 dev PG；生产库另议
export DEEPEVAL_PER_ATTEMPT_TIMEOUT_SECONDS=25 DEEPEVAL_RETRY_MAX_ATTEMPTS=1
# 候选①：现行判官 + 采样通道
uv run python scripts/calibrate_judge_live.py --gold /tmp/gold_validity_pilot.json \
  --samples 5 --candidate "flash-vote-k5" --workers 3 --out /tmp/bakeoff_flash_vote_k5.json
# 候选②：基线另一可服务者
EVAL_MODEL="openai/glm-5.3-flash" uv run python scripts/calibrate_judge_live.py \
  --gold /tmp/gold_validity_pilot.json --samples 5 --candidate "glm53-vote-k5" \
  --workers 3 --out /tmp/bakeoff_glm53_vote_k5.json
```

driver 已硬化：按 guidance 缓存 GEval evaluation_steps（51 个不同 criterion 只生成一次）、单次调用异常降级为 dropped（绝不伪造 fail 票）、k 必须奇数、`confidence_source` 逐条留痕。判读仍按分层门（balanced_accuracy ≥ 0.70 且分桶单调）；过门才勾 4.1 并由运维显式切 `EVAL_MODEL`，不过门继续如实挂账。
