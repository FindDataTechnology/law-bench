# judge-reliability Specification（delta）

## Purpose

判官可靠性契约：评分指令与被评内容显式分区、判官输出解析对结构性误读 fail-loud、修后校准闭环。判官可信度是评测生态（meta-eval、gold 声明闸、双通道评测）的地基。对应 `add-knowledge-bench-platform` 任务 4.1。

## ADDED Requirements

### Requirement: 评分指令与被评内容分区

判官评分链的 prompt SHALL 将「评分指令（rubric criteria）」与「被评内容（合同正文）」显式分区声明：判官 SHALL NOT 在被评正文内索要评分标记（PASS/FAIL 等评分记号属于评分链输出，不属于合同内容）；prompt 版本 SHALL 经既有 `generation_prompts` 版本化域落新版本行（不覆盖历史），provenance 记录修复动因。

#### Scenario: 正文与评分项分离
- **WHEN** 判官对一份分节齐全的合同评分
- **THEN** 判官不再向合同正文索要 PASS/FAIL 标记；评分针对评分项产出

### Requirement: 误读 fail-loud

判官输出的解析 SHALL 对三类结构性误读 fail-loud：①判官把评分标记写入「合同正文」语义域；②混淆评分项与正文字段引用；③输出契约外的结构。检测到任一 SHALL 判该次评分 invalid（不计入分数、不产生 gold 信号），SHALL NOT 静默放行或猜测纠偏——宁可无效不可假绿。

#### Scenario: 索要标记判 invalid
- **WHEN** 判官输出要求在被评合同里添加 PASS/FAIL 标记
- **THEN** 该次评分判 invalid 并留痕原因，不进入分数与 gold 信号

#### Scenario: 不静默纠偏
- **WHEN** 解析器无法确定输出归属（评分项 vs 正文）
- **THEN** 判 invalid 而非猜测纠偏

### Requirement: 修后校准闭环

修后判官 SHALL 在既有 gold 上重跑 live 校准（既有校准 driver），校准报告落库可查；验收判据 SHALL 为：结构性误读用例清零 + all_pass 回到合理区间（任务 4.1 verify 原文）；不达标 SHALL 如实记录差距再迭代，SHALL NOT 造绿。校准后判官（新 prompt 版本）方可被域包声明为 gold 信号源（沿既有未校准 judge 声明闸）。

#### Scenario: 修后校准落库
- **WHEN** 修复后运行 live 校准
- **THEN** 校准报告（按置信分档准确率矩阵+单调性）落库，误读用例清零与 all_pass 区间可查

#### Scenario: 未达标不造绿
- **WHEN** 校准结果仍有结构性误读用例
- **THEN** 任务如实记录差距继续迭代，校准报告如实呈现，不虚报完成
