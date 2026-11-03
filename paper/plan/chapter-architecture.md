# 章节架构（Chapter Architecture）

> 全篇写作的强制契约。质量门以此文件校验章节文件的存在性、最小长度、占位符策略与 agent provenance。
> `min_chars` 为非空白字符数下限。

## Required chapter files

- chapters/00_Abstract.md | min_chars=350 | agent=required | placeholders=yes
- chapters/01_Introduction.md | min_chars=1100 | agent=required | placeholders=no
- chapters/02_SystemDesign.md | min_chars=1200 | agent=required | placeholders=no
- chapters/03_KeyMethods.md | min_chars=1400 | agent=required | placeholders=no
- chapters/04_Experiments.md | min_chars=1400 | agent=required | placeholders=yes
- chapters/05_Discussion.md | min_chars=700 | agent=required | placeholders=yes
- chapters/06_Conclusion.md | min_chars=400 | agent=required | placeholders=yes
- chapters/07_References.md | min_chars=0 | agent=none | placeholders=no

合计下限约 6550 非空白字符，落在 5000–8000 字目标区间内。

## 占位符策略说明

- 引言、系统总体设计、关键方法三章**不得**出现未回填占位符：其素材全部来自仓库中已存在的设计文档与代码，无待补数据。
- 实验与结果分析、讨论、结论三章允许保留 `[待真实实验替换]` 标记，用于消融实验与裁判效度验证两处尚未运行的内容；摘要待正文完成后回写，允许占位。
- 投稿（`-Submission`）模式下所有占位符必须清零。

## 章节依赖与写作顺序

```
01_Introduction ──┐
02_SystemDesign ──┼──► 03_KeyMethods ──► 04_Experiments ──► 05_Discussion ──► 06_Conclusion ──► 00_Abstract
                  │
refs/evidence-map.md ──► 01（引言必须由证据地图驱动）
```

- 引言依赖 `refs/evidence-map.md` 与 `plan/chapter-blueprints/introduction-blueprint.md`。
- 实验章依赖 `plan/experiment-protocol.md`、`plan/review/method-experiment-traceability.md`、`tables/table-schema.md`、`figures/data-manifest.md`。
- 摘要最后写。

## 素材来源映射（写作 agent 的输入清单）

| 章节 | 主要素材 |
|---|---|
| 引言 | `refs/evidence-map.md`、`PRODUCT.md`、本文 outline 第 1 节 |
| 系统总体设计 | `docs/pipeline-architecture.md`、`docs/contract-generation-logic.md`、`docs/tag-driven-assembly.md`、`docs/evaluation-system.md` |
| 关键方法 | `docs/evaluation-system.md`（评分模型、多裁判）、`docs/rubric-mapping.md`、`src/eval/scoring.py`、`scripts/self_iterate.py`、`src/eval/law_refined_citations.py` |
| 实验与结果分析 | `docs/v4-final-results.md`（含过期表格，须按 `plan/progress.md` 口径校正）、`tables/table-schema.md`、提交 `644576e` 信息 |
| 讨论 | 实验章的失败分类学、`plan/progress.md` 的待办（效度与稳定性） |
| 结论 | 全篇 + `plan/project-overview.md` 的贡献条目 |

## 拒绝检查（每章通用）

- 正文出现过程性语言（"待回填""写作提示""本节模板"）→ 拒绝
- 以项目符号堆砌替代连贯论证段落 → 拒绝
- 声称超出素材支撑范围的结果（尤其把未运行的消融写成已验证）→ 拒绝
- 引用未在 `refs/evidence-map.md` 中登记的来源 → 拒绝
