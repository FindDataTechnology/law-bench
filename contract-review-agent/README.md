# Contract Review Agent (合同评审助手)

基于 LangGraph + 3 个 AI 模型的多模型合同评审服务，自动生成合同并提供法律、商业、完整性三重审查。

## 🌐 部署形态

服务自托管（Docker Compose / k8s 均可），默认端口：前端 3000、后端 8000，API 文档位于 `http://<backend-host>:8000/docs`。原公网演示实例已下线。

---

## 📋 功能概述

### 核心能力

| 功能 | 说明 |
|------|------|
| **合同生成** | 基于条款库自动生成完整的合同草案 |
| **3 重评审** | 法律准确性 × 商业公平性 × 完整性并行审查 |
| **双重评估** | Rubric 规则评估 + DeepEval 指标验证 |
| **历史记录** | 所有评审记录持久化存储，可查询回溯 |

### 支持的合同类型

- 买卖合同（sale）
- 租赁合同（lease）
- 服务合同（service）
- 其他...（可通过配置扩展）

---

## 🚀 快速开始

### 本地运行

```bash
# 1. 配置环境变量
cd <repo-root>/contract-review-agent
cp .env.example .env
# 编辑 .env 文件，填写你的 API KEY 和数据库配置

# 2. 启动服务
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# 3. 启动前端
cd frontend
npm install
npm run dev
```

访问 http://localhost:30830 即可使用。

### Docker 部署（推荐）

```bash
# 构建镜像
docker build -f Dockerfile.review-backend -t review-agent-backend:latest .

# 推送至 Harbor
docker tag review-agent-backend:latest harbor.local/law-bench/review-agent-backend:latest
docker push harbor.local/law-bench/review-agent-backend:latest

# 部署到 k3s
kubectl apply -f deploy/review-agent/backend-service.yaml
kubectl apply -f deploy/review-agent/backend-deployment.yaml

# 重启应用
kubectl rollout restart deployment review-agent-backend -n law-bench
```

---

## 🔧 环境配置

### .env 配置项

```bash
# === 三组评审员模型 ===
REVIEWER_1_MODEL=openai/kimi-k3          # 法律准确性评审员
REVIEWER_1_LENS=legal_accuracy
REVIEWER_1_NAME=Legal Reviewer

REVIEWER_2_MODEL=openai/qwen-3.7-plus    # 商业公平性评审员
REVIEWER_2_LENS=commercial_fairness
REVIEWER_2_NAME=Commercial Reviewer

REVIEWER_3_MODEL=openai/glm-5.2          # 完整性评审员
REVIEWER_3_LENS=completeness
REVIEWER_3_NAME=Completeness Reviewer

# === 填槽生成模型 ===
QUIZ_MODEL=openai/glm-5.2                 # 用于生成合同槽位问题

# === 起草 + 评估模型 ===
DRAFTER_MODEL=openai/qwen-3.7-plus        # 合同起草
EVAL_MODEL=openai/kimi-k3                  # 规则评估

# === OpenAI 兼容接口 ===
OPENAI_API_KEY=sk-your-api-key            # 你的 API Key
OPENAI_API_BASE=https://www.linjie.love/v1

# === PostgreSQL 数据库（law-bench 共用）===
DATABASE_URL=postgresql://app:CHANGEME@postgres.postgres.svc.cluster.local:5432/law_bench

# === 服务器配置 ===
HOST=0.0.0.0
PORT=8000
CORS_ORIGINS=http://localhost:30830,http://<retired-america-box-ip>:30830
```

---

## 📡 API 接口

### 运行合同评审

```bash
curl -X POST http://<retired-america-box-ip>:30831/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "生成一份农产品买卖合同",
    "contract_type": "sale",
    "scenario": "农产品买卖"
  }'
```

**响应示例**:
```json
{
  "thread_id": "chat-a1b2c3d4",
  "total_duration": 64.45,
  "draft": "【生成的合同内容】...",
  "reviews": [...],
  "synthesized_suggestions": [...],
  "eval_result": {
    "n_passed": 1,
    "n_criteria": 10,
    "summary": "..."
  },
  "deepeval_scores": {...},
  "node_timings": {
    "generate_v1": 3.35,
    "review_panel": 36.08,
    ...
  }
}
```

### 查询历史记录

```bash
# 列出最近记录
curl http://<retired-america-box-ip>:30831/api/agent-runs?limit=20

# 获取特定记录详情
curl http://<retired-america-box-ip>:30831/api/agent-runs/{run_id}
```

---

## 🏗️ 技术架构

### 系统架构

```
┌─────────────────────────────────────────────────────┐
│              Browser (http://:30830)                │
├─────────────────────────────────────────────────────┤
│  Frontend (Next.js 14 + Tailwind CSS)               │
│  • Chat Interface                                   │
│  • Results Dashboard                                │
└──────────────────────────┬──────────────────────────┘
                           │ HTTPS
┌──────────────────────────▼──────────────────────────┐
│       Backend (FastAPI + LangGraph)                 │
│  Port: 30831                                        │
├─────────────────────────────────────────────────────┤
│  LangGraph Graph                                    │
│  ├── generate_v1     → Generate contract draft      │
│  ├── review_panel    → 3 parallel reviewers         │
│  ├── synthesize      → Merge suggestions            │
│  ├── generate_quiz   → Generate slot questions      │
│  ├── generate_v2     → Final contract v2            │
│  ├── evaluate        → Dual evaluation              │
│  └── export          → Generate DOCX/PDF            │
└──────────────────────────┬──────────────────────────┘
                           │ PostgreSQL
┌──────────────────────────▼──────────────────────────┐
│             law_bench Database                      │
├─────────────────────────────────────────────────────┤
│  • pipeline_runs - Pipeline executions              │
│  • eval_runs - Evaluation results                   │
│  • agent_runs - Agent metrics                       │
│  • clauses - Contract clauses                       │
│  • rubrics - Evaluation criteria                    │
└─────────────────────────────────────────────────────┘
```

### 评审流程

1. **生成草稿** (`generate_v1`)
   - 从条款库组装合同草案
   - 提取所有 {{slot}} 占位符

2. **多模型评审** (`review_panel`)
   - 3 个评审员并行工作：
     - Legal Reviewer: 法律准确性检查
     - Commercial Reviewer: 商业公平性检查
     - Completeness Reviewer: 完整性检查

3. **综合建议** (`synthesize`)
   - 合并 3 个评审员的建议
   - 去重、严重度分级

4. **生成填槽问题** (`generate_quiz`)
   - 为每个 slot 生成自然语言问题
   - 便于用户理解并正确填写

5. **生成终稿** (`generate_v2`)
   - 应用用户填写的槽位值
   - 生最终成版合同

6. **双重评估** (`evaluate`)
   - Rubric 规则评估：✓/✗评分项
   - DeepEval 指标：幻觉/忠实度/槽位相关性

7. **导出文档** (`export`)
   - 生成 DOCX 和 PDF 格式合同

---

## 📊 数据模型

### agent_runs 表结构

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT | 主键 |
| thread_id | TEXT | 运行时线程 ID |
| contract_type | TEXT | 合同类型 |
| tags | JSONB | 标签（scenario, stance） |
| task_desc | TEXT | 任务描述 |
| node_timings | JSONB | 各节点耗时 |
| model_calls | JSONB | 模型调用记录 |
| review_suggestions | JSONB | 评审建议列表 |
| suggestions_applied | JSONB | 采纳的建议 |
| total_slots | INTEGER | 总槽位数 |
| human_filled_slots | INTEGER | 已填槽位数 |
| eval_run_id | BIGINT | Rubric 评估关联 ID |
| deepeval_scores | JSONB | DeepEval 结果 |
| total_duration | REAL | 总耗时（秒） |
| created_at | TIMESTAMPTZ | 创建时间 |

---

## 🔍 常见问题

### Q: 为什么需要 2-4 分钟完成一次评审？

A: 因为 3 个 LLM 模型需要并行执行，每次调用平均需要 10-15 秒。再加上合同生成、评估等步骤，总共约需 2-4 分钟。

### Q: 可以修改评审员模型吗？

A: 可以。修改 `.env` 中的 `REVIEWER_X_MODEL` 配置，然后重启服务即可。支持任何 OpenAI 兼容的 LLM。

### Q: 评审建议会直接影响合同生成吗？

A: 不会。当前版本中，评审建议仅作为参考反馈显示给用户。如需自动应用建议，可在后续版本中实现。

### Q: 如何自定义评估规则？

A: 通过规则管理后台 http://<retired-america-box-ip>:30820 可以创建/修改 rubric 规则。

---

## 🛠️ 故障排查

### 后端启动失败

```bash
# 检查数据库连接
psql $DATABASE_URL -c "SELECT 1"

# 查看日志
kubectl logs -l app=review-agent-backend -n law-bench --tail=100
```

### 前端加载失败

```bash
# 检查 CORS 配置
curl -I http://<retired-america-box-ip>:30830

# 检查浏览器控制台错误
```

### 评审超时

```bash
# 检查 LLM API 响应
curl https://www.linjie.love/v1/models

# 调整超时设置
# docker-compose.yml or K8s pod timeout
```

---

## 📞 技术支持

- **项目文档**: `/docs/` 目录
- **OpenAPI 文档**: http://<retired-america-box-ip>:30831/docs
- **代码仓库**: https://github.com/law-ai-official/law-bench/tree/main/contract-review-agent

---

## ⚖️ License

Copyright © 2024 Law Template Project. All rights reserved.
