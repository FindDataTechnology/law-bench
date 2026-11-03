## Task Packet: 03_KeyMethods

- **Scope**: 写关键方法章（4 小节），目标文件 `paper/chapters/03_KeyMethods.md`
- **Target chapter file and exclusive owner**: `paper/chapters/03_KeyMethods.md`（仅此 agent 可写）
- **Files to read**: `docs/evaluation-system.md`、`docs/rubric-mapping.md`、`src/eval/scoring.py`、`scripts/self_iterate.py`、`src/eval/law_refined_citations.py`、`paper/refs/evidence-map.md`、`paper/plan/experiment-protocol.md`、`paper/plan/outline.md`
- **Files allowed to edit**: `paper/chapters/03_KeyMethods.md`（仅此一个文件）
- **Required skills**: `writing-core`；`evidence-driven-writing` 的引用规则（引用只允许 evidence-map 中已登记条目）
- **Evidence/data inputs**: 证据地图 R8（G-Eval 评估方法）、R9（LLM 裁判偏置）、R12（裁判模型差异）、R13（Self-Refine）、R14（Reflexion）；协议细节见 `plan/experiment-protocol.md`
- **Required artifacts**: `paper/chapters/03_KeyMethods.md`
- **Required argument chain (段落角色)**:
  - 3.1 全通过式二值评估协议：逐条评审项独立裁判 → all-pass 聚合 → 与加权评分的对比论证（为何二值化逼迫生成端逐点做对）→ 多裁判与置信度设计（对 R9/R12 的回应）
  - 3.2 评估驱动的条款级自愈：触发条件（全票失败 vs 多数失败）、合并而非替换的更新策略、轮次上限与停机条件；与 R13/R14 的迭代自改进范式的区别（外部裁判信号驱动、条款级而非全文重写）
  - 3.3 标签驱动的条款组装：法律主题标签体系、标签选择与槽位填充的分离、法条引用强化的**设计描述**
  - 3.4 质量信号的回归能力：以全通过率作为可比较基线，支撑提示词横评与变更前后不回退检测
- **Minimum prose length**: 1400 非空白字符
- **Prohibited structure**: 模块清单式罗列；用公式/伪代码替代论证段落；过程性语言
- **Rejection checks**:
  1. 声称法条引用强化（C5）有效 → 拒绝（E7 未运行，只能写设计）
  2. 出现实验结果数字 → 拒绝（数字属实验章）
  3. 引用 R1–R15 之外来源 → 拒绝
  4. 3.2 未说明与 Self-Refine 类方法的区别 → 拒绝（须回应 R13/R14）
- **Validation commands**: 非空白字符数 ≥1400；引用标记数 ≥3；列表行数 ≤3
- **Required handoff format**: status、改动文件路径、论点链摘要、未解决缺口、自审
