# 任务：add-judge-misread-remediation

> apply 期实查修订：prompt 修复主体已以 v2-structure 在产（11-03 引入），本任务清单收窄为域化补账+解析硬化+校准实跑。

## 1. prompt 域化补账

- [x] 1.1 `v2-structure` 规则文本迁入 generation_prompts 域（judge_scoring_v2-structure 版本行+provenance inherits 记录；insert-only seeder 不覆盖 operator 编辑）
- [x] 1.2 `build_judge_criteria` 改按域查询注入，域不可用回落模块常量（评审链永不断，字节等同）；EVAL_PROMPT_VERSION 语义保留（域版本标签）

## 2. 解析硬化（fail-loud 单点）

- [x] 2.1 `_classify_structural_soundness` 检测（marker_in_contract 高置信 zh/en 归因+否定守卫、CONFIDENCE 违约→contract_violation、success+空 reasoning）；invalid verdict + invalid_reason 留痕
- [x] 2.2 invalid 从分数分母剔除、n_invalid/invalid_rate 顶层新增、全 invalid 强制 all_pass=False（宁无效不假绿）；消费方核查 6 处（run/compare/store/review/export/self_iterate）无 crash，invalid 天然不进 gold 信号（_agrees 只认 pass/fail）

## 3. 校准闭环实跑

- [x] 3.1 gold pair 导出实查：/tmp/gold_validity_pilot.json 已在（11-03 v4-validity-pilot 导出件，108 对，human 94/14，QC 过）——零新导出
- [x] 3.2 live calibration driver 复跑（v2-structure + fail-loud）报告落库——**已实跑（run id 8，eval_runs meta 通道）**：108 对全量 108 调用零错误，judge=openai/deepseek-v4.1-flash（token.finddatatech.cloud relay，11-03 校准同款端点，凭据自 law-bench-server/.env 旧产线拷贝，gitignored）；agree 65/108=0.602、单调 true、all_pass=False 如实；分档：106/108 no-confidence、[0.9,1.0] n=2 acc=0.5、其余桶 n=0
- [x] 3.3 验收判据核对（不达标如实，不造绿）：**结构性误读（假绿路径）已堵**——新屏把不可验证输出如实标 invalid 不再计入分数（宁无效不假绿达成）；**all_pass 未回合理区间**（0.602 < 0.70）——**第二轮数据驱动定谳：置信自报链路级不可靠**。宽容化假设被数据否决：105/108 根本无 CONFIDENCE token（非格式变体/位置问题——解析宽容无 token 可解析）；prompt 层遵从率≈3%（3/108），同款 prompt 同款端点两次复现（11-03 与本轮）——GEval 的 deepeval 输出模板吞掉自定义尾标要求，flash 级模型在此链上产出不了可校准置信信号。**工程边界定谳：非 prompt 迭代可修，属判定通道选型问题**（带原生置信/logprob 的通道，或分档矩阵改 human_pass 分层一致率）——另立 add-judge-model-selection 提案。4.1 保持不勾、差距与边界如实挂账

## 4. 回归与收口

- [x] 4.1 既有评测套件零回归（scores dict 增量兼容：n_invalid/invalid_rate 新键；compare 单稿格 cell 可能带 invalid 字符串如实记录）
- [x] 4.2 全量回归 1302 绿 + strict 绿（kernel domain-free + public hygiene 双闸 OK）
- [ ] 4.3 4.1 勾选（**未达成、挂账不销**）：结构性误读清零已达成、校准闭环已跑通；0.602<0.70 旧门差距已被 `add-judge-model-selection` 的**分层门**重新定谳——run 8 存档在新门下 balanced=0.7713 过门但 kappa=0.2352 且 105/108 无置信（旧世界空转），采样通道 pilot（run 5/6）balanced 0.6944/0.50 均不过门；relay 退化致全量 bake-off 未跑通（11-07 凌晨复盘仍退化：flash 三次 40s 读超时、glm53 502/503；证据与该 change 的「恢复后一键重跑配方」见归档 design.md 附录二）。生产判官不切换（镜像 sha-a41f38d 已上产，分层门与采样通道在产）；blueprint 台账已更新终态；解禁路径=更强上游/判官口径轮/维持 silver-only
