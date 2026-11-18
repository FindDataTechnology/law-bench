## Task Packet: 04_Experiments

- **Scope**: 写实验与结果分析章（5 小节），目标文件 `paper/chapters/04_Experiments.md`
- **Target chapter file and exclusive owner**: `paper/chapters/04_Experiments.md`（仅此 agent 可写）
- **Files to read**: `paper/plan/experiment-protocol.md`、`paper/plan/review/method-experiment-traceability.md`、`paper/tables/table-schema.md`、`paper/figures/data-manifest.md`、`docs/v4-final-results.md`、`paper/plan/outline.md`
- **Files allowed to edit**: `paper/chapters/04_Experiments.md`（仅此一个文件）
- **Required skills**: `experiment-results-planning`（要点：真实数据与 mock 数据的边界、表数据契约、结果章去污染）
- **Evidence/data inputs**: 见下方"权威数字"，全部为已完成的运行（E1–E4）
- **Required artifacts**: `paper/chapters/04_Experiments.md`
- **Required argument chain (段落角色)**:
  - 4.1 实验设置：数据集（43 类 = 19 有名 + 24 无名）、评估协议（逐条评审项 × 3 裁判、all-pass 聚合）、生成与裁判配置、并发配置、单次运行声明
  - 4.2 主结果：全通过率与逐类结果表（表 1），分组报告具名/非具名
  - 4.3 阈值敏感性：FAIL_CONF_THRESHOLD 0.99→0.67 解锁的 8 个类型（表 2），论证"多数失败"比"全票失败"更贴近真实缺陷
  - 4.4 失败案例分析：两类结构墙 + 4 个仍失败类型的逐项分析（表 3）
  - 4.5 工程约束：并发实验（表 4），限流按账号而非按模型计量的发现
- **Minimum prose length**: 1400 非空白字符
- **Prohibited structure**: 结果章出现"实验目的""表位""回填模板""讨论提示"等过程性语言；用表格替代论证段落；把未运行的实验写成已验证

### 权威数字（必须使用，不得改写）

- 主结果：**39/43 全通过（91%）**；具名 **18/19（95%）**；非具名 **21/24（88%）**
- 仍失败 4 类：lease 9/10、land_transfer 10/11、film_production 9/11、service 9/11
- 第 5 轮突破 4 类：partnership 10/10（第 5 轮）、property_service 10/10（第 5 轮）、company_formation 9/9（第 1 轮）、private_equity_fund 11/11（第 4 轮）
- 0.67 阈值解锁 8 类（表 2 数据）：loan 6/9→9/9（1 轮）、construction 6/10→10/10（2 轮）、bailment 8/9→9/9（1 轮）、gift 7/9→9/9（2 轮）、transport 8/9→9/9（2 轮）、entrustment 9/10→10/10（1 轮）、warehousing 9/10→10/10（1 轮）、work 8/9→9/9（1 轮）
- 并发：36 并发 → property_service 0/10（限流级联）；12 并发 → 无 429

### 逐类结果表的构造方法（关键）

`docs/v4-final-results.md` 的正文表格是 **2026-08-11 的过期快照（35/43）**，不得直接复制。正确做法：
1. 取该表的全部逐类行作为底稿（其中 35 类标 ✅、8 类标 ❌）；
2. 按上条"第 5 轮突破 4 类"把 partnership、property_service、company_formation、private_equity_fund 改为 ✅ 并填入对应分数与轮次；
3. 最终 ✅ 39 行、❌ 4 行（lease、land_transfer、film_production、service）；
4. 表注写明：数据来源为提交 `644576e` 的运行记录；**逐类结果的权威导出版待从评估库导出后替换**（替换责任人：S3 阶段）。

- **Rejection checks**:
  1. 使用 35/43 或 16/19 等过期数字 → 拒绝
  2. 把 E5–E8（自愈消融、标签消融、法条强化消融、裁判效度）写成已验证结果 → 拒绝；如需提及须标 `[待真实实验替换]`
  3. 未声明"单次运行" → 拒绝
  4. 出现过程性语言 → 拒绝
- **Validation commands**: 非空白字符数 ≥1400；出现"39/43"与"18/19"；四张表齐备；无 "实验目的" 等词
- **Required handoff format**: status、改动文件路径、论点链摘要、未解决缺口、自审
