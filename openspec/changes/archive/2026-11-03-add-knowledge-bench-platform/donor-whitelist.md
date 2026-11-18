# Donor Whitelist — law-bench-server 资产挑入（task 1.1）

供体：`/Users/chengsishi/finddata/law-bench-server/`（SMB 拷贝，HEAD 2f3125e，2026-11-02 复制）。
审查日：2026-11-02。审查方式：逐文件列表 + 凭据模式扫描（api_key/token/secret/password/Bearer/sk-）+ PII 扫描（电话/邮箱/证件号）+ 合同 docx 正文抽验。

## 结论：准入（12 类 54 文件）

| 路径 | 文件数 | 审阅结论 |
|---|---|---|
| `README.md` | 1 | 准入。**canonical 仓无 README**（10-31 拷贝缺失），供体版是公开仓 README（9.6K，含安全说明段），为唯一可用版本 |
| `contracts/generate.js` | 1 | 准入。docx 生成脚本（docx skill 规范），无凭据、无端点 |
| `contracts/软件服务与定制开发合同.docx` | 1 | 准入。**全占位符空白模板**（甲方/乙方/统一社会信用代码等全部为【请填写】，无真实当事方） |
| `contracts/软件服务与定制开发合同.pdf` | 1 | 准入。上项 docx 的 PDF 渲染，元数据为空 |
| `paper/chapters/*.md` | 8 | 准入。论文章节源（00_Abstract…07_References），作者署名为团队本人（有意署名，非 PII 泄露） |
| `paper/figures/**`（py/svg/png/csv/manifest） | 17 | 准入。论文图（架构图/通过率分布/阈值解锁）+ 底层 V4 数据（仅聚合计数：runs/max_iter/reached_all_pass/last_n_*，无客户数据、无文本样本） |
| `paper/plan/**` | 16 | 准入。论文写作过程文档（大纲/蓝图/stage-gates/同行评审记录） |
| `paper/refs/evidence-map.md`、`paper/tables/table-schema.md` | 2 | 准入。引用证据图与表格 schema |
| `paper/初稿.md`、`paper/初稿_en.md` | 2 | 准入。论文中/英全文源 |
| `paper/law-bench论文初稿.docx`+`.pdf`（中英各一对） | 4 | 准入。初稿.md/en 的构建产物（论文交付件） |
| `paper/build_docx.py` | 1 | 准入。docx 构建脚本，无凭据 |
| `openspec/changes/add-knowledge-bench-platform/**` | 5 | 准入。本 change 四件套 + 本白名单（随本次提交入库） |

## 排除（带理由）

| 路径 | 理由 |
|---|---|
| `paper/.render/`（18）+ `.render_cn/`（19）+ `.render_en/`（21）共 58 PNG | 派生构建产物（docx/pdf 的页面渲染），可再生，且使仓库膨胀 ~14M |
| `.DS_Store` | macOS 垃圾文件 |
| `.env`、`ssh-config.json`、`.git/**`、全部 `.claude/`、`.codex/`、`.zcode/`、`.impeccable/`、`.firecrawl/`、`.venv/`、`.mcp.json`、`__pycache__` 等供体其余一切 | **永不入公共仓**：凭据（供体 `.git/config` 内嵌 gitee 明文 token）、本地工具状态、虚拟环境。本次未拷入，白名单制下默认排除 |

## 复核记录

- 凭据模式扫描：contracts+paper 文本件零命中（仅初稿_en.md 英文摘要句子含单词 "benchmark" 触及宽松词面，非凭据）。
- PII 扫描：电话/邮箱/证件号模式零命中。
- 合同 docx 抽验：全部字段占位符，无真实主体。
- V4 数据 JSON 抽验：仅聚合计数字段。
