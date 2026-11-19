# 提案：判官结构性误读修复与修后校准（4.1）

## Why

`add-knowledge-bench-platform` 收口时唯一未勾的实活（任务 4.1）：现行判官（`EVAL_MODEL`）存在结构性误读——混淆「合同正文」与「评分项」、在合同里索要 PASS/FAIL 标记、误读字段——自认误读压低评估分上限且单次评分波动大（`docs/evaluation-system.md` §11 已知限制首条）。判官可信度是整个评测生态的地基：meta-eval 校准、gold 信号源声明闸、双通道评测全部以判官产出为输入。基础设施已就绪（live calibration driver `scripts/calibrate_judge_live.py` + 4 模型校准发现 + 用户裁定的 gold threshold 0.70），缺的是 prompt/解析层的修复本身与修后校准闭环。

## What Changes

> **apply 期实查修订（2026-11-06）**：prompt 修复主体**已在产**——`_JUDGE_STRUCTURE_RULES`（角色分离/注入防御/字段纪律/置信自报四条）于 11-03 随任务 4.2/4.3 引入（`EVAL_PROMPT_VERSION="v2-structure"`），晚于 §11 缺陷清单写下时间；任务 4.1 注记停留在旧世界。本 change 收窄为**剩余两刀**：

- **解析硬化（fail-loud）**：判官输出的解析对三类结构性误读 fail-loud——①判官把评分标记写入「合同正文」语义域（marker_in_contract）；②评分项与正文字段引用归属歧义（ambiguous_reference）；③输出契约违约（contract_violation，含缺 CONFIDENCE 尾标）。检测到任一判该次评分 invalid：不计入分数、不产生 gold 信号、留 reason 痕——宁可无效不可假绿。invalid 率纳入校准报告监控。
- **prompt 域化补账**：`v2-structure` 规则文本从 `scoring.py` 模块常量迁入 `generation_prompts` 域（type=judge_scoring 版本行 + provenance），评审链按版本查询注入（缺省最新、回滚=指定旧版本）——修复内容不变，归属补账。
- **修后校准闭环实跑**：prod review pilot gold pair 导出 → live calibration driver 复跑（v2-structure 判官 + fail-loud 解析）→ 校准报告落库 → 验收判据核对（结构性误读用例清零 + all_pass 回到合理区间 = 任务 4.1 verify 原文）。
- 非目标：换判官模型（4 模型校准发现供选型另裁）、all-pass 放大噪声结构性修复（§11 第二条另立）、多 judge 集成。

## Capabilities

### New Capabilities

- `judge-reliability`: 判官可靠性——评分指令/被评内容分区契约、输出解析 fail-loud、修后校准闭环与验收判据

### Modified Capabilities

- `generation-prompts`: 评分链 prompt 版本化（新版本行 + provenance），不新增机制——沿既有存储/查询/版本需求

## Impact

- **代码**：判官评分链 prompt（`generation_prompts` 域内新版本）+ 判官输出解析硬化（`src/eval/` 评分链单点）+ `scripts/calibrate_judge_live.py` 复跑产出新校准报告。
- **数据**：prompt 新版本行；校准报告落库（meta-eval 既有表）；零 schema 变更。
- **风险**：prompt 迭代可能多轮——验收判据（误读用例清零 + all_pass 合理区间）不达标则如实记录差距再迭代，不造绿。
