## Task Packet: 05_Discussion

- **Scope**: 写讨论章（3 小节），目标文件 `paper/chapters/05_Discussion.md`
- **Target chapter file and exclusive owner**: `paper/chapters/05_Discussion.md`（仅此 agent 可写）
- **Files to read**: `paper/chapters/04_Experiments.md`（结果与失败分类学）、`paper/plan/experiment-protocol.md`（已完成/未完成实验清单）、`paper/plan/review/method-experiment-traceability.md`（未覆盖项）、`paper/refs/evidence-map.md`（R10、R15）、`paper/plan/outline.md`（第 5 节）
- **Files allowed to edit**: `paper/chapters/05_Discussion.md`（仅此一个文件）
- **Required skills**: `writing-core`；`evidence-driven-writing` 的引用规则
- **Required artifacts**: `paper/chapters/05_Discussion.md`
- **Required argument chain (段落角色)**:
  - 5.1 为什么二值化是有效的质量信号：从"平均分掩盖短板"到"逐点做对"的行为差异；二值化的诊断职能由通过项数承担（呼应实验章的论证）
  - 5.2 测量可靠性的边界：裁判分裂意味着什么；何时是生成缺陷、何时是测量噪声；与 LLM 裁判可靠性研究的关系（R10、R15）
  - 5.3 局限性：**必须**包含——(a) 裁判效度尚未通过人工标注子集验证，测量工具未自证；(b) 结果为单次运行记录，多次运行的稳定性待补；(c) 自愈机制与标签机制各自的增益未被消融分离；(d) 评估集集中于中文法域
- **Minimum prose length**: 700 非空白字符（目标 800，不要超 1000）
- **Prohibited structure**: 把未运行的实验写成已验证；项目符号堆砌；过程性语言；机械过渡词；空壳强调句；正文加粗
- **Rejection checks**:
  1. 未把裁判效度未验证列为局限 → 拒绝
  2. 出现 R10/R15 之外的引用 → 拒绝
  3. 引入实验章未报告的新结果 → 拒绝
- **Validation commands**: 非空白字符数 700–1000；列表行数 0；引用标记 ≥2
- **Required handoff format**: status、改动文件路径、论点链摘要、未解决缺口、自审
