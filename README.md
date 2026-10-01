# law-bench · 中文法律合同起草与评测工作台

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](pyproject.toml)
[![PostgreSQL](https://img.shields.io/badge/store-PostgreSQL-336791)](src/settings.py)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**law-bench** 是「[寻数·识律](#关于寻数识律)」法律 AI 产品线的合同评测与起草基座：它维护一个**法条锚定的条款语料库**，通过**标签驱动组装**生成合同，用 **LLM 评审（rubric 评分）** 度量合同质量，并以**自愈管线**和**提示词 A/B 对比**持续迭代——起草、评测、改进在一个闭环里完成。

> 邻近的合同生成器负责「产出草稿」，law-bench 负责「度量草稿」：每一条起草策略的变化，都要经过 rubric 评审的量化验证才会合入。

## 核心能力

| 能力 | 说明 |
|------|------|
| **条款语料库** | 43 类中国合同的种子条款（[data/clause_seeds/](data/clause_seeds/)），带法条引用、标签维度（场景 `scenario`、立场 `stance` 等）、三级来源（base / tagged / custom）与人工审核工作流 |
| **标签驱动组装** | 按合同类型 + 标签组合装配母版，槽位（`{{slot}}`）由 LLM 或规则填充，输出 Markdown / DOCX / PDF |
| **LLM 评审** | rubric × criteria 逐条判定（PASS/FAIL + 理由），多评审模型并行、429/503 退避——限流永远不允许变成 criterion FAIL |
| **自愈管线** | `generate → fill → evaluate → improve` 迭代至达标（LangGraph 驱动），最佳迭代自动落库 |
| **提示词 A/B 对比** | compare runs：多提示词 × 多草稿，产出 criteria × prompts 通过率矩阵 |
| **法规目录** | 3 万+ 部中国法律条目（别名整理、条文级引用解析、废止法律的承继映射），生成合同时可内嵌条文级引用 |
| **人工复核** | 评审结论的盲标注、标注一致性 QC、gold 导出 |
| **多种接入** | Web 工作台（OIDC 登录）、公共只读 API（X-API-Key + 限流）、MCP server（37 个工具）、CrewAI CLI |

## 系统架构

```
                    ┌────────────────────────────────────────────┐
                    │                接入层                       │
   Web 工作台 ──────┤  src/web/app.py   (Logto OIDC 登录 + RBAC)  │
   公共只读 API ────┤  src/web/public_app.py (API Key + 限流)     │
   MCP server ──────┤  fd-coding-law-bench-mcp/ (FastMCP, 37 工具)│
   CLI ─────────────┤  main.py (CrewAI 多智能体起草)              │
                    └───────────────┬────────────────────────────┘
                                    │
        ┌───────────────┬───────────┴──────────┬─────────────────┐
        ▼               ▼                      ▼                 ▼
  PostgreSQL      S3 兼容对象存储          LLM（OpenAI 兼容     Elasticsearch
  （条款/rubric/   （RustFS/MinIO，        端点：方舟/OpenRouter/ （可选，条款
   prompt/评测      合同制品与模板，         自建 relay），按角色   分块 RAG 检索）
   运行记录；        读 minio_* 环境变量）    配置 intake/drafter/
   schema 幂等                              auditor/judge 模型
   自动创建）
```

- **PostgreSQL** 是唯一必需的外部服务：所有表以 `CREATE TABLE IF NOT EXISTS` 幂等创建，首次运行自动建表，无需迁移脚本。
- **对象存储**用于合同制品（DOCX/PDF）与母版模板，任何 S3 兼容服务（RustFS、MinIO 等）皆可。
- **LLM** 通过任意 OpenAI 兼容端点接入，起草（intake / drafter / auditor）与评审（judge）可分别指定模型与温度。
- **Elasticsearch**（可选）支撑条款分块 RAG 检索；不配置则检索降级，其余功能不受影响。
- **Logto**（可选，[docs.logto.io](https://docs.logto.io)）仅 Web 工作台登录需要；CLI / MCP / 评测管线不依赖它。

## 快速开始

### 前置条件

- Python 3.12–3.13 与 [uv](https://docs.astral.sh/uv/)
- PostgreSQL 15+（必需）
- 可选：S3 兼容对象存储（制品渲染）、Elasticsearch（RAG）、Logto（Web 登录）

### 步骤

```bash
# 1. 安装依赖
uv sync

# 2. 配置环境
cp .env.example .env
#    必填：OPENAI_API_KEY / OPENAI_API_BASE（任意 OpenAI 兼容端点）
#          database_url（PostgreSQL DSN）
#    其余（对象存储、RAG、Logto、模型角色）按需填写，见 .env.example 注释

# 3. 建库（schema 首次运行自动创建）
createdb law_bench

# 4. CLI 起草一份合同（CrewAI 多智能体：受理 → 起草 → 审校）
uv run python main.py "起草一份买卖合同，甲方为某科技公司，乙方为某贸易公司，标的为办公设备采购" out.md

# 5. 跑测试（conftest 会按 database_url 自动创建/回收每测试独立的数据库）
uv run pytest
```

### 启动 Web 工作台

Web 工作台采用**登录门禁（fail-closed）**：未配置 OIDC 时进程拒绝启动。自建一个 Logto（或任何兼容 OIDC 的 IdP），在 `.env` 中补齐：

```bash
LOGTO_ENDPOINT=https://your-logto-host        # 不带 /oidc 后缀
LOGTO_CLIENT_ID=...                           # Logto 应用 ID
LOGTO_CLIENT_SECRET=...
LOGTO_REDIRECT_URI=http://localhost:8010/auth/callback
LOGTO_SCOPES=openid profile email content:read content:write admin
LOGTO_API_RESOURCE=https://your-api-resource  # Logto API Resource 标识
AUTH_SESSION_SECRET=$(openssl rand -hex 32)   # 稳定随机串，轮换会使全部会话失效
APP_BASE_URL=http://localhost:8010

uv run uvicorn src.web.app:app --port 8010
```

### 启动 MCP server（agent 接入）

```bash
# 见 fd-coding-law-bench-mcp/README.md（含全部 37 个工具的说明）
uv run --project . python -m fd_coding_law_bench_mcp
```

### 子项目：合同评审助手

[contract-review-agent/](contract-review-agent/)：基于 LangGraph 的多模型合同评审服务（法律准确性 × 商业公平性 × 完整性三重审查），独立部署，有自己的 README。

## 目录结构

```
src/
  clauses/        条款库（种子导入、三级组装、标签、审核工作流）
  contracts/      合同生成与制品（Markdown/DOCX/PDF，槽位填充）
  eval/           LLM 评审（rubric CRUD、多评审打分、compare、自愈管线、人工复核）
  law_catalog/    法规目录（别名、条文引用解析、承继关系、审计）
  search/         条款分块 RAG（Elasticsearch，可选）
  web/            FastAPI 工作台 + 公共只读 API（OIDC / API Key）
  settings.py     全部配置项（一律环境变量，无内置默认密码）
data/
  clause_seeds/   43 类合同种子条款（YAML）
  finetune/       微调数据管线 schema 与产物（见 微调说明.md）
db/               内置种子（rubric/标准/提示词，含 Harbor v0.20.0 衍生规则）
fd-coding-law-bench-mcp/   FastMCP server（37 工具，包装 src.* 原地实现）
contract-review-agent/     LangGraph 合同评审子项目
docs/            设计与运维文档（评测体系、组装逻辑、管线架构、V4 结果…）
tests/           pytest 套件（本地 PG 即可运行，无外部网络依赖）
```

> 内部部署配置（k8s 清单、Jenkins、ArgoCD、OpenSpec 变更管理目录）不随开源发布；开源部署使用根目录的 `Dockerfile`（单镜像，默认服务完整应用，`PUBLIC_API=1` 时服务只读公共 API）。

## 文档索引

- [docs/evaluation-system.md](docs/evaluation-system.md) — 评测体系设计
- [docs/tag-driven-assembly.md](docs/tag-driven-assembly.md) — 标签驱动组装
- [docs/pipeline-architecture.md](docs/pipeline-architecture.md) — 自愈管线架构
- [docs/contract-generation-logic.md](docs/contract-generation-logic.md) — 合同生成逻辑
- [docs/v4-final-results.md](docs/v4-final-results.md) — V4 全量评测结果
- [docs/web-usage-guide.md](docs/web-usage-guide.md) — Web 工作台使用指南
- [docs/api_instruction.md](docs/api_instruction.md) / [docs/api-evaluate.md](docs/api-evaluate.md) — 公共 API 使用
- [微调说明.md](微调说明.md) — 微调数据管线
- [fd-coding-law-bench-mcp/README.md](fd-coding-law-bench-mcp/README.md) — MCP 工具全景

## 安全说明

- 全部凭据走环境变量（`.env`，已 gitignore）；**仓库不含任何内置密码或密钥**，`.env.example` 中只有占位符。
- Web 工作台 fail-closed：OIDC 未配置即拒绝启动；会话 cookie 由 `AUTH_SESSION_SECRET` 签名。
- 公共 API 以加盐哈希存 API Key，进程内令牌桶限流。
- 合同文本属于敏感数据：评测遥测默认关闭（`DEEPEVAL_TELEMETRY_OPT_OUT=true`）。

## 关于寻数·识律

law-bench 是**寻数·识律**（FindData 法律 AI 产品线）的合同评测与起草基座，由寻数团队（[FindDataTechnology](https://github.com/FindDataTechnology)）维护。识律产品线的对外服务部署于 `*.finddatatech.cloud`；本仓库为其核心引擎与工作台的开源版本。

## License

[MIT](LICENSE) © 2026 FindDataTechnology（寻数·识律）。
