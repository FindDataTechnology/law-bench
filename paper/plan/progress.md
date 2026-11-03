# 写作进度

## 阶段状态（截至 2026-09-21）

| 阶段 | 状态 | 说明 |
|---|---|---|
| S0 立项 | ✅ 完成 | 题目、结构、数据口径已确认；`plan/` 全部硬门控产物已落盘 |
| S1 证据 | ✅ 完成 | 15 条文献逐条核实；证据地图与引言段落蓝图就绪 |
| S2 方法 | ✅ 完成 | 系统总体设计、关键方法两章完成（含输入→输出流程与范式对照） |
| S3 实验 | ⚠️ 部分完成 | 协议、可追溯性、表格契约、图件清单齐备；**裁判效度、消融、多次运行未执行** |
| S4 写作 | ✅ 完成 | 7 章全部由独立 agent 写作，正文合计 7,972 字符（不含摘要），图 2、图 3 已产出 |
| S5 评审 | ✅ 完成 | 质量门脚本通过；自审报告见 `plan/review/paper-peer-review.md` |

## 最终产物

| 文件 | 内容 | 规模 |
|---|---|---|
| `chapters/00_Abstract.md` | 摘要与关键词 | 590 |
| `chapters/01_Introduction.md` | 引言 | 1340 |
| `chapters/02_SystemDesign.md` | 系统总体设计 | 1558 |
| `chapters/03_KeyMethods.md` | 关键方法 | 1548 |
| `chapters/04_Experiments.md` | 实验与结果分析 | 正文 2125 + 表 2253 |
| `chapters/05_Discussion.md` | 讨论 | 937 |
| `chapters/06_Conclusion.md` | 结论与展望 | 668 |
| `figures/04_experiments/*.png/.svg` | 图 2、图 3 | 450 DPI |
| `figures/02_system_design/fig1_architecture_prompt.md` | 图 1 提示词与 Mermaid 源 | 待渲染 |

正文（不含摘要与表格）合计 7,972 非空白字符，落在 5000–8000 字目标内。

## 关键决策记录

1. **题目选择**：三个候选中选定系统型题目，理由是系统论文体裁匹配且"评估闭环 + 自愈式生成"是系统区别于其他合同生成工具的定位。
2. **相关工作不单列章节**：按 paper-orchestration 对计算机类论文的规定融入引言。
3. **数据口径锁定**：43 类为评估集口径；`contract_types.json` 全集 66 类中 23 类未评估、不计入；权威结果 39/43。
4. **过期表格处理**：`docs/v4-final-results.md` 正文表格为 2026-08-11 快照（35/43），论文不引用该表格，改以提交 `644576e` 的逐类记录为底稿。
5. **压缩决策**：初稿正文合计 15,417 字符，超出期刊要求近一倍，由原作者 agent 压缩至 7,972，压缩原则为保留论点、证据、方法条件与边界。
6. **段落格式**：按质量门的段落数要求（每章 ≥6 个实质段落）在自然话题边界分段，只插空行、不改文字（分段前后去空白哈希一致）。

## 阻塞项（投稿前必办）

- [x] **裁判效度验证**：✅ 2026-09-22 完成——生产库批次 `v4-validity-pilot-202609`（126 对×双盲标）：标注者间一致率 85.7%（κ=0.522），人-判官一致率 36.5%（κ=0.075），分歧高度单向（157 vs 3）；已写入正文 4.5 节、表 5、摘要、5.2/5.3 与结论
- [ ] **多次运行稳定性**：43 类重复 3 次，报告通过名单一致性与 mean ± std（需补跑 LLM 实验）
- [ ] **消融实验**：自愈开/关、法条引用强化 v2/v1（`compare_run` 已就绪；生产库无干净双臂，须新跑）
- [ ] **朴素基线对比**：单次提示词直出作为基线，同评估集比较（需补跑）
- [x] **R3/R4 全文确认**：✅ 2026-09-22 核实——LegalBench（162 任务）中合同相关任务（ContractNLI/CUAD/MAUD）均为对既有合同文本的分析（NLI/条款识别/并购协议理解），无起草类；LexEval（23 任务）生成层仅含摘要生成、司法分析生成、法律翻译、开放问答，无合同起草任务。论文引言的空白声明成立（主源：两基准官方仓库与论文 Table 1）
- [ ] **中文文献补齐**：需作者提供知网题录 3–5 篇
- [x] **权威逐类结果导出**：✅ 2026-09-22 交叉核对完成——生产库战役状态为第 4 轮快照（36/40），第 5 轮未入库；表 1/表 3 维持提交 `644576e` 口径并已在注释中说明核对结论，「—」计数仍待第 5 轮数据补导出
- [x] **图 1 渲染**：✅ 已由 `fig1_architecture.py`（matplotlib 六层架构）产出 PNG/SVG（450 DPI），manifest 原状态记录过时已更正
- [x] **署名**：史成思（第一作者）、蓝枫兰（第二作者）已入标题块；单位/邮箱留待作者补
- [x] **英文版**：`初稿_en.md` 与中文版同步产出（2026-09-22）

## Capability-use audit

### Capability-use audit（S0–S5 全流程）

- **Required skills**: `using-research-writing`（入口路由）、`paper-orchestration`（阶段门控与多 agent 分章）、`brainstorming-research`（S0 立项）、`evidence-driven-writing`（引言）、`literature-review`（文献检索与证据地图）、`writing-core` / `writing-chapters`（章节写作）、`experiment-results-planning`（实验协议与数据边界）、`figures-python`（图 2、图 3）、`figures-diagram`（图 1 提示词）、`verification`（质量门与程序化核验）、`peer-review`（S5 自审）
- **Skills actually used**: 上述全部 11 个，另加 `environment-setup` 的判断（未调用：matplotlib 用 uv 临时依赖解决，无需 conda）
- **Inputs consumed**: `PRODUCT.md`、`docs/pipeline-architecture.md`、`docs/contract-generation-logic.md`、`docs/tag-driven-assembly.md`、`docs/evaluation-system.md`、`docs/rubric-mapping.md`、`docs/v4-final-results.md`、`src/contracts/classification.py`、`src/eval/scoring.py`、`scripts/self_iterate.py`、`src/eval/law_refined_citations.py`、提交 `644576e` 记录、`refs/evidence-map.md` 的 R1–R15
- **Inputs not used and why**: `latex-output`（期刊未要求 LaTeX，`latex-templates/` 为空）；`statistical-analysis`（本稿为单次运行记录，无统计检验可做；待 M2 补跑后启用）；`prompts-collection`（去 AI 化规则已内联在各写作任务包的禁止项中）
- **Artifacts produced**: `paper/` 下 7 个章节文件、`plan/` 下 12 个契约文件（含 7 份任务包）、`refs/evidence-map.md`、`tables/table-schema.md`、`figures/` 下 4 个图件产物与 2 个数据文件
- **Verification run**: `research_quality_gate.ps1`（**通过**，仅余允许的占位符警告）；程序化核验数字口径、违禁词、引用范围、段落数、分段前后哈希一致性；图件数据与表 1 同源核验（43/39/4）
- **Remaining risk**: 裁判效度未验证（M1）、单次运行（M2）、消融缺失（M3）、研究空白的证据强度（M4）、中文文献缺口（M5）、无外部基线（M6）——全部已记入 `plan/review/paper-peer-review.md` 的投稿前必办清单
