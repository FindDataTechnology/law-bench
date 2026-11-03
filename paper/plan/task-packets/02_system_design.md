## Task Packet: 02_SystemDesign

- **Scope**: 写系统总体设计章（4 小节），目标文件 `paper/chapters/02_SystemDesign.md`
- **Target chapter file and exclusive owner**: `paper/chapters/02_SystemDesign.md`（仅此 agent 可写）
- **Files to read**: `docs/pipeline-architecture.md`、`docs/contract-generation-logic.md`、`docs/tag-driven-assembly.md`、`docs/evaluation-system.md`、`src/contracts/classification.py`、`paper/plan/outline.md`、`paper/plan/project-overview.md`
- **Files allowed to edit**: `paper/chapters/02_SystemDesign.md`（仅此一个文件）
- **Required skills**: `writing-core`（要点：正文优先连贯段落、去 AI 化、术语准确）
- **Evidence/data inputs**: 上述设计文档；数据集口径见 `paper/plan/project-overview.md` 的"数据口径"节
- **Required artifacts**: `paper/chapters/02_SystemDesign.md`
- **Required argument chain (段落角色)**:
  - 2.1 总体架构：以数据流为主线（条款语料 → 标签组装 → 槽位填充 → 多裁判评估 → 自愈迭代 → 运行记录），说明每层的输入/处理/输出
  - 2.2 数据模型：合同类别（43 类 = 19 有名 + 24 无名）、条款（正文 + 法律主题标签 + 法条引用）、评审项（rubric/criteria）、运行记录
  - 2.3 三条流水线：标准自愈、自动淘汰（learn 节点）、标签迭代（suggest 只读 / apply 串行可回滚），并说明并发安全规则
  - 2.4 部署形态：持久化、对象存储、向量检索、MCP 服务端与 Web 工作台双入口
- **Minimum prose length**: 1200 非空白字符
- **Prohibited structure**: 只罗列模块名而不写数据流；"由三层组成""包括若干模块"后缺少输入/输出与设计理由；项目符号堆砌；过程性语言
- **Rejection checks**:
  1. 任一组件缺少输入/处理/输出说明 → 拒绝
  2. 出现未参与评估的 23 类合同被计入 43 类 → 拒绝（口径见 project-overview）
  3. 出现实验结果数字 → 拒绝（数字属实验章）
- **Validation commands**: 非空白字符数 ≥1200；列表行数 ≤3；含"图 1"引用
- **Required handoff format**: status、改动文件路径、论点链摘要、未解决缺口、自审
