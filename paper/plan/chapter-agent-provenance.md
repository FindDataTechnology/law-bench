# 章节写作溯源（Chapter Agent Provenance）

> paper-orchestration 多 agent 门控要求：每章由独立 agent 写作，记录 agent、输入、输出路径与评审状态。
> 无 provenance 记录的章节不予接受。质量门脚本校验本文件的"接受"标记。

## 写作 agent 记录

| 章节 | 写作 agent | 任务包 | 输入 | 输出路径 | 评审状态 |
|---|---|---|---|---|---|
| chapters/00_Abstract.md | 控制器（支持性文件，非主章） | — | 全部章节定稿内容 | `paper/chapters/00_Abstract.md` | status=ACCEPTED（摘要按计划最后回写） |
| chapters/01_Introduction.md | agent_6ef2c2b5-95e4-433f-b66d-8d4dd3e23fdf | `plan/task-packets/01_introduction.md` | `refs/evidence-map.md`、`plan/chapter-blueprints/introduction-blueprint.md`、`PRODUCT.md` | `paper/chapters/01_Introduction.md` | status=ACCEPTED（初稿 2244 → 压缩 1340；控制器复核引用落位与段落角色） |
| chapters/02_SystemDesign.md | agent_ac302251-546f-4c51-8af6-a1ce3a5c8514 | `plan/task-packets/02_system_design.md` | `docs/pipeline-architecture.md`、`docs/contract-generation-logic.md`、`docs/tag-driven-assembly.md`、`docs/evaluation-system.md`、`src/contracts/classification.py` | `paper/chapters/02_SystemDesign.md` | status=ACCEPTED（初稿 3904 → 压缩 1558；控制器复核 17 组件输入/处理/输出齐备） |
| chapters/03_KeyMethods.md | agent_c3092888-4d16-4164-9d0d-5a35ea67a23a | `plan/task-packets/03_key_methods.md` | `docs/evaluation-system.md`、`docs/rubric-mapping.md`、`src/eval/scoring.py`、`scripts/self_iterate.py`、`src/eval/law_refined_citations.py` | `paper/chapters/03_KeyMethods.md` | status=ACCEPTED（初稿 4167 → 压缩 1548；复核 3.2 范式区别与 3.3 有效性限定保留） |
| chapters/04_Experiments.md | agent_ff7b8b8c-12ca-4473-adf1-238230425fdb | `plan/task-packets/04_experiments.md` | `plan/experiment-protocol.md`、`plan/review/method-experiment-traceability.md`、`tables/table-schema.md`、`docs/v4-final-results.md` | `paper/chapters/04_Experiments.md` | status=ACCEPTED（正文 5102 → 2125，四表保留；复核 39/43 口径与过期数字零出现） |
| chapters/05_Discussion.md | agent_5bd1a2bf-1cd8-43bc-a2a3-cc2e34cebfbf | `plan/task-packets/05_discussion.md` | `chapters/04_Experiments.md`、`plan/experiment-protocol.md`、`plan/review/method-experiment-traceability.md` | `paper/chapters/05_Discussion.md` | status=ACCEPTED（四项局限齐备；未引入实验章之外的新结果） |
| chapters/06_Conclusion.md | agent_929e5395-032d-4c3c-97bd-ebca493cd08b | `plan/task-packets/06_conclusion.md` | `chapters/04_Experiments.md`、`plan/project-overview.md`、`plan/experiment-protocol.md` | `paper/chapters/06_Conclusion.md` | status=ACCEPTED（零引用、零新数字；展望四项与未运行实验一致） |

## 写入所有权

- 每章仅一个 agent 可写，写权限互斥，未发生并发写同一文件。
- 控制器（主 agent）只写 `plan/`、`tables/`、`figures/` 下的契约文件与 `chapters/00_Abstract.md`（支持性文件）。

## 压缩轮次

- 四章因篇幅超出期刊要求（初稿合计 15,417 字符 vs 目标约 8,000）由原作者 agent 压缩，压缩原则：保留论点、证据、方法条件与边界，只删冗余修饰、重复表述与可推出的推论。
- 压缩后正文合计 7,972 字符（不含摘要），落在 5000–8000 字目标内。

## 控制器独立复核（不采信 agent 自述）

| 复核项 | 方法 | 结果 |
|---|---|---|
| 章节文件与架构一致 | 质量门脚本 | 7 个章节文件齐备，无多余或缺失 |
| 结果数字口径 | 程序化检索 | 39/43、18/19、21/24 正确；过期数字 35/43、16/19 零出现 |
| 违禁词 | 程序化检索 | 压缩后各章机械过渡词与空壳强调句零命中 |
| 引用范围 | 程序化检索 | 仅 R1–R15，无范围外引用 |
| 过程性语言 | 质量门脚本 | 零命中 |
