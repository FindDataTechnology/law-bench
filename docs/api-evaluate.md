# 合同评估 API 调用说明

异步 REST API:提交合同文本,按指定 rubric(评估规则集)评估,轮询获取结果。

- **Base URL**: `http://<retired-america-box-ip>:30820`
- **交互式文档**: `http://<retired-america-box-ip>:30820/api/docs`(Swagger UI,可在线试调)

---

## 端点总览

| 方法 | 路径 | 说明 | 状态码 |
|------|------|------|--------|
| POST | `/api/evaluate` | 提交评估任务(异步) | 202 / 400 / 404 / 422 |
| GET | `/api/evaluate/{run_id}` | 查询单个评估结果 | 200 / 404 |
| GET | `/api/evaluate` | 列出最近的评估记录 | 200 |

---

## 1. 提交评估 — `POST /api/evaluate`

`Content-Type: multipart/form-data`

### 表单字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `rubric` | string | ✅ | rubric 名称(如 `contract_sale_v2`)。可用 `GET /api/rubrics` 查看 |
| `contract_text` | string | 二选一 | 合同正文(内联文本) |
| `contract_file` | file | 二选一 | 合同文件上传(`.md` / `.txt`,UTF-8) |

> `contract_text` 与 `contract_file` **必须提供其一**,否则返回 400。

### 示例

**内联文本:**

```bash
curl -X POST http://<retired-america-box-ip>:30820/api/evaluate \
  -F "rubric=contract_sale_v2" \
  -F "contract_text=甲方与乙方就买卖事项达成如下协议……"
```

**文件上传:**

```bash
curl -X POST http://<retired-america-box-ip>:30820/api/evaluate \
  -F "rubric=contract_sale_v2" \
  -F "contract_file=@/path/to/contract.md"
```

### 成功响应 — `202 Accepted`

```json
{
  "run_id": 1,
  "status": "pending"
}
```

立即返回 `run_id`,评估在后台进行。客户端用 `run_id` 轮询结果。

### 错误响应

| 状态码 | 场景 | 响应体 |
|--------|------|--------|
| 400 | 未提供 `contract_text` 或 `contract_file` | `{"error": "Either contract_text or contract_file is required"}` |
| 404 | `rubric` 不存在 | `{"error": "Rubric not found: '<name>'"}` |
| 422 | 表单校验失败(如缺 `rubric`) | FastAPI 标准校验错误 |

---

## 2. 查询评估结果 — `GET /api/evaluate/{run_id}`

### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `run_id` | int | 提交时返回的 run_id |

### 响应状态机

返回的 `status` 字段反映评估生命周期:

```
pending ──▶ running ──▶ completed
                  │
                  └────▶ failed
```

| status | 含义 |
|--------|------|
| `pending` | 已入队,等待后台执行 |
| `running` | 正在评估(调用 LLM judge 中) |
| `completed` | 评估完成,结果就绪 |
| `failed` | 评估出错,见 `error_message` |

### 示例

```bash
curl http://<retired-america-box-ip>:30820/api/evaluate/1
```

### 完成响应 — `200 OK`

```json
{
  "id": 1,
  "rubric_name": "contract_sale_v2",
  "status": "completed",
  "contract_text": "甲方与乙方……",
  "score": 0.0,
  "all_pass": false,
  "n_passed": 0,
  "n_criteria": 10,
  "results": {
    "rubric": "contract_sale_v2",
    "score": 0.0,
    "max_score": 1.0,
    "all_pass": false,
    "n_criteria": 10,
    "n_passed": 0,
    "summary": "0/10 criteria passed. Missed 10 - FAIL.",
    "judge_model": "kmodel_latest",
    "scored_at": "2026-08-03T21:41:01.139033+00:00",
    "criteria_results": [
      {
        "id": "party_identification",
        "title": "是否清晰识别全部合同主体……",
        "verdict": "fail",
        "reasoning": "……"
      }
    ]
  },
  "error_message": null,
  "judge_model": "kmodel_latest",
  "created_at": "2026-08-03T21:40:45.076376+00:00",
  "completed_at": "2026-08-03T21:41:01.139306+00:00"
}
```

### 字段说明

**顶层字段:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | int | run_id |
| `rubric_name` | string | 使用的 rubric |
| `status` | string | 评估状态 |
| `contract_text` | string | 提交的合同原文 |
| `score` | float \| null | 1.0(全部通过)/ 0.0(有未通过);未完成时为 null |
| `all_pass` | bool \| null | 是否全部 criteria 通过 |
| `n_passed` / `n_criteria` | int \| null | 通过数 / 总数 |
| `results` | object \| null | 完整评估结果(含 `criteria_results` 数组) |
| `error_message` | string \| null | 失败时的错误描述 |
| `judge_model` | string \| null | 使用的 LLM judge |
| `created_at` / `completed_at` | string | 提交 / 完成时间(ISO 8601) |

**`results.criteria_results[]` 每项:**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | criterion 标识 |
| `title` | string | criterion 中文描述 |
| `verdict` | string | `"pass"` / `"fail"` |
| `reasoning` | string | judge 给出的理由(若 judge 调用出错,错误信息会附在此处) |

### 错误响应

| 状态码 | 场景 | 响应体 |
|--------|------|--------|
| 404 | run_id 不存在 | `{"error": "API eval run not found: <id>"}` |

---

## 3. 列出评估记录 — `GET /api/evaluate`

### 查询参数

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `limit` | int | 20 | 返回最近 N 条(按 id 倒序) |

### 示例

```bash
curl "http://<retired-america-box-ip>:30820/api/evaluate?limit=10"
```

### 响应 — `200 OK`

返回数组(不含 `contract_text` 和 `results`,精简版):

```json
[
  {
    "id": 2,
    "rubric_name": "contract_sale_v2",
    "status": "completed",
    "score": 0.0,
    "all_pass": false,
    "n_passed": 0,
    "n_criteria": 10,
    "error_message": null,
    "judge_model": "kmodel_latest",
    "created_at": "2026-08-03T21:45:00.000000+00:00",
    "completed_at": "2026-08-03T21:45:16.000000+00:00"
  }
]
```

---

## 典型调用流程(Python)

```python
import time
import requests

BASE = "http://<retired-america-box-ip>:30820"

# 1. 提交评估
with open("contract.md", "rb") as f:
    resp = requests.post(
        f"{BASE}/api/evaluate",
        data={"rubric": "contract_sale_v2"},
        files={"contract_file": f},
    )
run_id = resp.json()["run_id"]
print(f"submitted: run_id={run_id}")

# 2. 轮询结果
while True:
    r = requests.get(f"{BASE}/api/evaluate/{run_id}").json()
    status = r["status"]
    print(f"status: {status}")
    if status in ("completed", "failed"):
        break
    time.sleep(3)

# 3. 读取结果
if status == "completed":
    print(f"score: {r['score']}, passed: {r['n_passed']}/{r['n_criteria']}")
    for c in r["results"]["criteria_results"]:
        print(f"  [{c['verdict']}] {c['id']}: {c['reasoning'][:80]}")
else:
    print(f"failed: {r['error_message']}")
```

---

## 备注

- **评估耗时**:取决于 rubric 的 criteria 数量,每个 criterion 一次 LLM 调用(并发 8 路),通常 10–60 秒。建议轮询间隔 3–5 秒。
- **judge 出错处理**:若 LLM judge 调用失败(如 relay 返回 500),该 criterion 的 `verdict` 记为 `fail`,`reasoning` 末尾会附 `[error: ...]`。整个 run 仍标记为 `completed`(不阻塞),不视为 API 失败。
- **数据存储**:所有评估记录存于 `api_eval_runs` 表,与 MCP 用的 `eval_runs` 表分离。
- **无清理机制**:目前无 TTL,旧记录不会自动删除。
- **可用的 rubric**:调用 `GET /api/rubrics` 查看全部 rubric 及其 criteria 数量。

---

## V4:多评审(multi-judge)评估

V4 起,`evaluate_contract` 之外新增 `evaluate_with_multi_judge`(`src/eval/scoring.py`),
用 **N 个评审模型并行打分 + 多数表决**,抑制单评审噪声(引用类 criterion 尤其明显)。

```python
from src.eval.scoring import evaluate_with_multi_judge

result = evaluate_with_multi_judge(
    contract_text=body,
    rubric_name="contract_sale_v3",
    task_desc="起草一份农产品买卖合同",
    judge_models=["openai/kimi-k3", "openai/glm-5.2", "openai/qwen-3.7-plus"],
    max_workers=1,   # 串行!并发会触发 relay 限流噪声
)
```

### 评分语义

- 每个 criterion 由全部 judge 投票,`pass` 多数决 → 共识 verdict。
- `confidence` = 共识票数 / judge 数:3 评审时取 1.0(全票)或 0.67(2:1)。
- `score = 1.0` 当且仅当 **全部 criterion 通过** 且非 low_confidence。
- 结果含 `n_unanimous_pass` / `n_majority_pass` / `n_failures` 明细,
  每个 criterion 带 `per_judge_reasoning`(各评审原始理由)。

### 降级策略

- 单个 judge 失败不崩溃:记入 `judge_errors`,其余 judge 继续。
- 仅剩 2 个 judge:要求 2/2 全票;仅剩 1 个:置 `low_confidence=true`,score 强制 0。
- 全部失败:抛 `RuntimeError`。

### 实践经验(来自 19 类有名合同自迭代)

- **judge 选型**:避免推理型模型(如 deepseek-v4-pro,思考耗时 10 倍);
  推荐 kimi-k3 + glm-5.2 + qwen-3.7-plus 组合。
- **串行执行**:`max_workers=1`。多评审本身已是 3 倍调用量,
  再并发会触发 relay 限流,失败 criterion 混入噪声。
- **自迭代停止条件**:只剩 judge 分裂(0.67 置信)的 fail 时即为噪声地板,
  继续迭代只会来回震荡,应停止(见 `scripts/self_iterate.py`)。

---

## V4:标签体系(tag schema)

V4 精简了 tag 维度,`tag_vocab_list()` 返回:

| 维度 | 范围 | 说明 |
|------|------|------|
| `source` | 全局 | `base` / `tagged` / `custom`(条款来源,自动维护) |
| `stance` | 全局 | `pro_a` / `pro_b` / `balanced`(立场) |
| `scenario` | 按类型 | 业务场景(如 `农产品买卖`、`住宅租赁`) |
| `legal_topic` | 按类型 | 条款对应的 rubric criterion id(每类型 10 个左右) |

**已删除的死维度**:`strength` / `risk` / `mandatory`(旧数据保留,新条款不再使用)。

### stance 别名

`tag_validate()` 与组装的 custom 条款过滤都会先做别名解析:

| 输入 | 解析为 |
|------|--------|
| `pro_seller` | `pro_a` |
| `pro_buyer` | `pro_b` |

即 `contract_generate(tags={"stance": "pro_seller"})` 等价于 `stance="pro_a"`,
同时匹配 `pro_a` 与 `pro_seller` 两种存量数据。

### legal_topic 的作用

`legal_topic` 把条款挂到 rubric criterion 上,自迭代据此定位"哪个 criterion
挂了 → 该补哪类条款"。回填由 `scripts/backfill_legal_topics.py` 完成,
覆盖率校验用 `scripts/verify_topic_coverage.py`(有缺口时退出码非 0)。

---

## V4:自迭代闭环(self-iteration)

`scripts/self_iterate.py` 把"生成 → 多评审 → 补条款"串成闭环:

```
生成合同 → 串行多评审 → 取全票 FAIL(conf≥0.99)的 criterion
        → LLM 基于现有 custom + base 条款内容合并生成补充条款
        → create/update + 审批全部 tag 维度 → 重新生成评估
        → 直到 all_pass 或达到 max_rounds
```

```bash
# 单类型
python3 -u scripts/self_iterate.py sale --max-rounds 3 \
  --judges openai/kimi-k3 openai/glm-5.2 openai/qwen-3.7-plus

# 批量(顺序执行,per-type 日志 + 增量汇总)
python3 -u scripts/self_iterate_batch.py lease gift loan --max-rounds 3 \
  --summary batch_named_a.json
```

报告写入 `output/self_iterate/<type>_report.json`。注意:

- **合并而非替换**:补充条款合并进已有 custom 条款(`update_clause`),
  避免覆盖 base 的丰富内容(sale 权利义务条款曾因此丢检验期限)。
- **`-u` 必加**:管道/后台运行时 Python stdout 是块缓冲,不加看不到进度。
