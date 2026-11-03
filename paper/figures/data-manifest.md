# 图件清单（Figure Data Manifest）

> 硬门控产物：数据类图表必须先有数据文件与生成脚本，再写正文引用。

| Figure | 类型 | 内容 | 数据文件 | 真实/mock | 数据源 | 脚本 | 产出 | 状态 |
|---|---|---|---|---|---|---|---|---|
| 图 1 | 架构图 | law-bench 总体架构与数据流 | 无（示意） | — | `docs/pipeline-architecture.md` | `figures/02_system_design/fig1_architecture.py`（matplotlib 六层架构） | `fig1_architecture.png` / `.svg`（450 DPI） | ✅ 已产出 |
| 图 2 | 数据图 | 43 类合同全通过结果分布（具名/非具名分组） | `figures/data/fig2_pass_distribution.csv`（43 行） | 真实 | 提交 `644576e` 记录 + `src/contracts/classification.py` | `figures/04_experiments/fig2_pass_distribution.py` | `fig2_pass_distribution.png` / `.svg`（450 DPI） | ✅ 已产出 |
| 图 3 | 数据图 | 阈值下调解锁的 8 个类型的通过评审项比例 | `figures/data/fig3_threshold_unlock.csv`（8 行） | 真实 | 提交 `644576e` 阈值变更前后逐类记录 | `figures/04_experiments/fig3_threshold_unlock.py` | `fig3_threshold_unlock.png` / `.svg`（450 DPI） | ✅ 已产出 |

## 数据同源核验

- 图 2 的数据文件由 `src/contracts/classification.py` 的 19 具名 + 24 无名集合与提交 `644576e` 的 4 个失败类型集合生成，计数为 43 行 / 39 通过 / 4 失败，与论文表 1 的合计行一致。
- 图 3 的数据文件取自表 2 的 8 行（阈值变更前后分数与轮次），逐值对应。
- 表 5（裁判效度混淆矩阵）的数据来自生产评估库人工审查批次 `v4-validity-pilot-202609`，指标文件 `figures/data/judge_validity_pilot.csv`：49+157+43+3=252 判定，(49+43)/252=36.5% 人-判官一致率，206/252=81.7% 人工通过率，与正文 4.5 节逐值一致。
- V4 逐类结果的生产库交叉核对：战役包装行（`pipeline_runs`，task_desc 含 V4 self-iteration）为第 4 轮后中间快照（40 类中 36 类曾达全通过），第 5 轮突破类型未入库；交叉核对产物存 `figures/data/v4_authoritative_prod.json` 与 `v4_campaign_prod.json`（2026-09-22 导出），逐类口径仍以提交 `644576e` 记录为权威。
- 两图数据均为真实运行记录，**不含 mock 数据**。

## 复现命令

```bash
cd paper
uv run --no-project --with matplotlib --with numpy python figures/04_experiments/fig2_pass_distribution.py
uv run --no-project --with matplotlib --with numpy python figures/04_experiments/fig3_threshold_unlock.py
```

## 分享用文档构建

| 产物 | 生成方式 | 说明 |
|---|---|---|
| `law-bench论文初稿.docx` | `python build_docx.py`（python-docx，学术场景排版） | 投稿/分享用；含 3 张嵌入图件与 4 张表格；表头行设 `tblHeader`（跨页重复）、全行 `cantSplit`（行内不断裂） |
| `law-bench论文初稿.pdf` | Word COM 导出（`ExportAsFixedFormat`） | 预览/打印用；18 页 |
| `.render/page-NN.png` | pymupdf 按 110 DPI 渲染 | 视觉检查用页面图，非交付物 |

**排版规范**（依据 documents 技能的学术场景）：正文宋体小四 12pt、1.5 倍行距、首行缩进 2 字符、两端对齐、纯黑；章标题黑体三号居中、节标题黑体四号左对齐；图题与表题宋体五号居中；页边距上下 2.54cm、左 3.00cm、右 2.50cm。

**已知待优化**（不影响使用）：表 1 的"合同类别（类别键）"列偏窄，长类别名（如 `entrustment`、`equity_holding_in_trust`）在单元格内折行；如需更紧凑可在 Word 中调整该列列宽。

## 注意事项

- 若后续新增消融图（自愈开/关、法条强化 v2/v1），数据文件名须以 `mock_` 开头，图注标注 `PLANNING DATA - replace before submission`，正文对应段落保留 `[待真实实验替换]`。
- 图 1 不得出现具体主机名、域名、集群名（按 AGENTS.md 对退役基础设施的处理要求）。
- 正文引用图件的编号须与表 1–4 一致；图不得替代本应存在的论证段落。
