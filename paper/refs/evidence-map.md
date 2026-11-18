# 证据地图（Evidence Map）

> 引言与相关工作段落的证据—论点—引用位置映射。**只允许使用题名、摘要、DOI 元数据或已读取全文中的信息。**
> 所有条目于 2026-09-21 通过 CrossRef API、arXiv 页面或 arXiv API 逐条核实，元数据真实可追溯。
> 本论文相关工作不单列章节，全部融入引言的论证链（按 paper-orchestration 对计算机类论文的规定）。

## 纳排标准

- **纳入**：与中文/法律合同生成、法律领域大模型评测、LLM-as-judge 评估协议、迭代式自改进相关，且元数据可核实。
- **排除**：区块链智能合约（solidity 代码）相关（与法律合同文本不同域）；无法核实元数据的条目一律不写。
- **中文文献**：AI 无法检索知网，按 literature-review 硬门控，需由作者提供来源后再纳入（见文末待补清单）。

## 证据表

| Source ID | Citation | Source type | Abstract-level finding | Usable fact | Supported claim | Citation slot | Risk |
|---|---|---|---|---|---|---|---|
| R1 | Dahl M, Magesh V, et al. Large Legal Fictions: Profiling Legal Hallucinations in Large Language Models. Journal of Legal Analysis, 2024. DOI 10.1093/jla/laae003 | 期刊论文 | 系统性刻画法律领域大模型的幻觉现象 | 法律领域存在系统性幻觉，且与提问方式相关 | 大模型在法律领域存在可靠性缺陷，需要外部质量校验 | 引言-P1（问题背景） | 低 |
| R2 | Ogunde F. Legal large language models (LLMs): legal dynamos or "fancifully packaged ChatGPT"? Discover Artificial Intelligence, 2025. DOI 10.1007/s44163-024-00167-8 | 期刊论文 | 对法律大模型能力的批判性审视 | 法律大模型的能力宣称需要更严格的检验 | 现有法律大模型缺乏可复现的质量度量 | 引言-P2（现有路线瓶颈） | 低 |
| R3 | Guha N, Nyarko J, Ho D E, et al. LegalBench: A Collaboratively Built Benchmark for Measuring Legal Reasoning in Large Language Models. arXiv:2308.11462, 2023 | 预印本/基准 | 协作构建的法律推理评测基准 | 法律评测需要任务化、可复现的基准 | 法律领域评测已有基准化传统，但集中于推理任务而非生成质量 | 引言-P2（研究现状） | 中（需全文确认任务类型构成） |
| R4 | Li H, Chen Y, Ai Q, et al. LexEval: A Comprehensive Chinese Legal Benchmark for Evaluating Large Language Models. arXiv:2409.20288, 2024 | 预印本/基准 | 面向中文法律的综合评测基准 | 中文法律评测已有综合基准，覆盖认知层次任务 | 中文法域已有评测基准，但以问答/推理类任务为主，缺少面向合同起草质量的闭环评测 | 引言-P2（研究空白的关键对照） | 中（需全文确认是否含生成类任务） |
| R5 | Yue S, Chen W, Wang S, et al. DISC-LawLLM: Fine-tuning Large Language Models for Intelligent Legal Services. arXiv:2309.11325, 2023 | 预印本/系统 | 微调法律大模型以服务智能法律应用 | 法律智能服务需要领域适配 | 领域适配是既有主流路线，与本文的"评估闭环"路线互补 | 引言-P2（现有技术路线之一） | 低 |
| R6 | Carneiro-Diaz V, Grille-Zallas A, Lage-Etchart D. Automated legal analysis of rental contract clauses using large language models. SoftwareX, 2025. DOI 10.1016/j.softx.2025.102337 | 期刊论文 | 用大模型自动分析租赁合同条款 | 合同条款级分析可用大模型实现 | 条款级自动化在法律合同上可行，本文进一步把它用作生成质量的度量单位 | 引言-P2 / 方法-3.1（条款级粒度） | 低 |
| R7 | Deroy A, Ghosh K, Ghosh S. Investigating legal question generation using large language models. Artificial Intelligence and Law, 2025. DOI 10.1007/s10506-025-09452-y | 期刊论文 | 研究法律问题生成任务 | 法律文本生成任务已被系统研究 | 法律生成任务的评测通常面向单一任务，缺少跨合同类别的统一质量信号 | 引言-P2 | 低 |
| R8 | Liu Y, Iter D, Xu Y, et al. G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment. arXiv:2303.16634, 2023 | 预印本/方法 | 提出基于 GPT-4 的 NLG 评估方法，与人类判断对齐更好 | 大模型可作评估器，且与人类判断有较好对齐 | 本文的评审项裁判机制建立在 G-Eval 式评估之上 | 方法-3.1（评估协议来源） | 低 |
| R9 | Zheng L, Chiang W-L, Sheng Y, et al. Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena. arXiv:2306.05685, 2023 | 预印本/方法 | 系统检验 LLM 作为裁判的可靠性，指出位置/冗长等偏置 | LLM 裁判存在可测量的偏置 | 单一裁判不可靠，需要多裁判与置信度机制 | 方法-3.1（多裁判设计依据） | 低 |
| R10 | Li Y, Chen X, Dolata M. LLM-as-a-Judge for mental support: A meta-evaluation using domain-specific platform data. Electronic Markets, 2026. DOI 10.1007/s12525-026-00890-3 | 期刊论文 | 领域数据上对 LLM 裁判做元评估 | 裁判本身需要元评估（与人类判断比对） | 裁判效度验证是方法成立的必要环节（本文列为局限） | 讨论-5.2（测量可靠性边界） | 低 |
| R11 | Vasilev Y, Raznitsyna I, et al. Evaluating Medical Text Summaries Using Automatic Evaluation Metrics and LLM-as-a-Judge Approach: A Pilot Study. Diagnostics, 2025. DOI 10.3390/diagnostics16010003 | 期刊论文 | 在医学文本摘要上比较自动指标与 LLM 裁判 | LLM 裁判已在专业领域用于质量评估 | LLM 裁判在专业领域已有应用先例，本文将其用于法律合同 | 引言-P2（跨领域方法迁移） | 低 |
| R12 | Cassola-Bacallao J, Morales-Donaire J, et al. Benchmarking LLM-as-a-Judge Models for 5W1H Extraction Evaluation. Electronics, 2026. DOI 10.3390/electronics15030659 | 期刊论文 | 对多个 LLM 裁判模型做基准比较 | 裁判模型之间性能存在差异 | 裁判选择影响评估结果，支持多裁判设计 | 方法-3.1 | 低 |
| R13 | Madaan A, Tandon N, Gupta P, et al. Self-Refine: Iterative Refinement with Self-Feedback. arXiv:2303.17651, 2023 | 预印本/方法 | 模型用自身反馈迭代改进输出 | 迭代自反馈可提升生成质量 | 本文的自愈迭代属于该范式，但由外部裁判信号驱动、且作用于条款级而非全文重写 | 方法-3.2（自愈机制对照） | 低 |
| R14 | Shinn N, Cassano F, Berman E, et al. Reflexion: Language Agents with Verbal Reinforcement Learning. arXiv:2303.11366, 2023 | 预印本/方法 | 用语言化反馈做强化学习的智能体框架 | 语言化反馈可驱动智能体改进 | 与自愈机制同属反馈驱动改进范式 | 方法-3.2 | 低 |
| R15 | Deininger P, Slany W. Fixing, Breaking, or Faking It? An Execution-Calibrated Evaluation of LLM Vulnerability Patching ... and the Limits of LLM-as-Judge. Journal of Cybersecurity and Privacy, 2026. DOI 10.3390/jcp6050153 | 期刊论文 | 以执行校准评估补丁修复，并指出 LLM 裁判的局限 | LLM 裁判存在系统性局限 | 裁判可靠性上限是通用问题，本文观测到的"裁判分裂墙"与之呼应 | 讨论-5.2 | 低 |

## 研究空白论证（引言 P3 的证据要求）

空白陈述必须由多条文献共同支撑，不得由单一文献推出：

1. 法律领域大模型存在可靠性缺陷（R1、R2）→ 需要外部质量校验；
2. 法律评测已有基准化传统，但任务类型集中于问答/推理（R3、R4），合同起草质量缺少统一信号；
3. 合同条款级自动化已被验证可行（R6），法律文本生成任务已有研究（R7），但两者都未解决"改进是否真的有效"的可回归度量问题；
4. LLM 裁判可用但有偏置、需元评估（R8、R9、R10、R12、R15）→ 本文的多裁判+置信度设计正对此而设。

## 引用风险与待补

| 项 | 说明 |
|---|---|
| R3、R4 需全文确认 | 两者均标注为"中"风险：需确认其任务构成中是否包含合同生成类任务，避免引言中的空白陈述被审稿人反驳。**建议在 S5 前补读全文。** |
| 中文文献缺口 | 按 literature-review 硬门控，知网文献需作者提供。建议补：中文法学/计算机期刊中关于"法律大模型""合同智能审查""大模型自动评估"的近三年文献 3–5 篇，由作者检索后提供题录，我据实纳入。 |
| 未采纳条目 | 检索命中的区块链智能合约类（DeepDesc、CodeBC）、建筑能耗生成类等条目与本文域不符，已排除，不作为引用。 |
