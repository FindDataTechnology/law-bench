# 合同评估体系说明

本文档系统介绍合同评估体系：如何用 LLM-as-judge + 规则集（rubric）对一份起草好的合同打分、如何持久化与对比、以及评估如何嵌入自愈流水线。

> 核心代码：`src/eval/scoring.py`（评审主流程）、`src/eval/judge.py`（judge 构造）、`src/eval/rubric.py` + `rubric_crud.py`（rubric 管理）、`src/eval/store.py`（持久化）、`src/eval/compare.py`（prompt 对比）。MCP 工具层在 `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/tools/{evaluate,rubrics,compare,pipeline}.py`。

---

## 1. 总览

评估体系围绕一个方法论：**all-pass 二值评分**。一份合同只有「全部评审项都通过」才得 1.0，否则 0.0；不存在部分得分。这逼迫生成端把每个法律要点都做对，而非用长处掩盖短板。

```
drafted contract  ──┐
task_desc (可选)  ──┤── evaluate_contract(contract_text, rubric_name, task_desc)
rubric (N 条规则) ──┘        │
                             ├─ 每条规则一个 GEval(strict) judge ── 并发 ──┐
                             │                                              │
                             └─ 聚合 ◄────────────────── 逐条 pass/fail ───┘
                                    │
                                    └─► {score: 1.0 if all_pass else 0.0,
                                         n_passed / n_criteria,
                                         criteria_results: [{id,title,verdict,reasoning}]}
```

三条使用路径：
- **单次评估**：`contract_evaluate` 工具 / `evaluate_contract()`，评一份合同。
- **prompt 对比**：`compare_run` 工具 / `run_compare()`，固定合同类型+rubric+任务，变 prompt，横向对比。
- **自愈闭环**：`pipeline_run` 的 `evaluate -> check -> improve` 节点，用评估结果驱动合同自愈。

---

## 2. 评分模型（all-pass 二值）

`evaluate_contract`（`scoring.py:57`）的核心逻辑：

```python
n_total   = len(criteria_results)
n_passed  = sum(1 for r in criteria_results if r["verdict"] == "pass")
all_pass  = (n_passed == n_total)

score     = 1.0 if all_pass else 0.0     # 只有全过才 1.0
max_score = 1.0
```

- **每条规则**产出二值 `verdict`（`pass` / `fail`）+ `reasoning`（judge 给出的理由）。
- **任务分**只有 0.0 / 1.0 两档，等于 `all_pass` 标志。
- 同时记录诊断量 `n_passed` / `n_criteria`，便于看「差几条」。
- `summary` 形如 `"9/10 criteria passed. Missed 1 - FAIL."`。

这套打分刻意是「台阶式」的：9/10 与 0/10 同为 0.0 分，避免用高通过率掩盖单点缺失。比较两份合同时，真正可比的是 `n_passed` 与逐条 `criteria_results`，而非 `score`。

---

## 3. Rubric 体系

### 3.1 结构与字段映射

rubric 是「规则集」，每条规则三个字段。DB schema 存一套命名，评审器消费 harvey-labs 风格的另一套，在 `rubric.py:load_criteria` 里无 schema 变更地映射：

| DB `criteria` 列 | 评审器字段 | 含义 |
|---|---|---|
| `name` | `id` | 稳定标识（如 `ownership_transfer`） |
| `description` | `title` | 「检查什么」的人话陈述 |
| `guidance` | `match_criteria` | judge 据此判定的 **「PASS if … / FAIL if …」标准** |

一个 rubric = `rubrics` 表一行（`name, context, source, description`）+ `criteria` 表若干行（按 `ordinal` 排序）。

### 3.2 来源：harbor（只读） vs local（可写）

| `source` | `is_harbor` | 含义 |
|---|---|---|
| `harbor:v0.20.0` | true | 从 Harbor 种子导入，**只读**，任何 CRUD 写操作抛 `HarborReadOnlyError` |
| `local` | false | 本地创作，可经 `rubric_create` / `criterion_add` 等增删改 |

当前库内 harbor rubric 只有 2 条，且 context 非 contract（`task_quality` 评 benchmark 任务设计质量、`trial_behavior` 评 trial 行为），**不用于合同评估**。合同 rubric 全部是 `local`。

### 3.3 版本演进：v1 → v2 → v3

合同 rubric 命名 `contract_<type>_v<N>`，覆盖约 45 个合同类型，每类三个版本：

| 版本 | 标注 | 说明 |
|---|---|---|
| `v1` | （初始版） | 首版规则 |
| `v2` | 法律精修版 | 法律措辞精修 |
| `v3` | 优化判定版 | 优化 PASS/FAIL 判定指引，最新（2026-08-02 批次） |

每条 rubric 含 8–11 条规则。例如 `contract_sale_v3`（10 条）：标的物所有权转移、风险转移、检验与瑕疵担保等。

`pipeline_run` 不显式传 `rubric` 时，`default_rubric(type)`（`graph.py:69`）取该类型最高版本：匹配 `contract_<type>_v<N>` 选最大 `N`，否则取字典序最后的 `contract_<type>_*`。

> 合同类型与 rubric 版本独立演进：生成端按 `contract_type` 装配，评估端按 `contract_<type>_v<N>` 评审，二者通过类型 key 对齐。

### 3.4 Rubric CRUD（仅 local）

| 工具 | 作用 |
|---|---|
| `rubric_list` | 列出全部 rubric（`include_counts=true` 带 `criterion_count` / `is_harbor`） |
| `rubric_get` | 取一个 rubric 的元数据 + 有序规则 |
| `rubric_create` / `rubric_update` / `rubric_delete` | local rubric 增改删（harbor 报错） |
| `criterion_add` / `criterion_update` / `criterion_delete` / `criterion_reorder` | 规则级增改删与重排（`ordinal` 重编号） |

`criterion_add` 在末尾追加（next ordinal）；`criterion_delete` 后幸存规则重编号；`criterion_reorder` 需传入当前全部规则 id 的新顺序，否则校验报错。

---

## 4. Judge（LLM 评审器）

### 4.1 构造（`judge.py`）

judge 用 **deepeval 的 `GPTModel`**，指向项目自有的 OpenAI 兼容端点（Volcengine Ark），与起草 crew 共用一条网络路径与凭证：

```
EVAL_MODEL        : 模型 id（litellm 前缀，如 openai/glm-5.x，构造时剥掉 openai/ 前缀）
OPENAI_API_KEY    : 同 crew
OPENAI_API_BASE   : Ark 端点
EVAL_TEMPERATURE  : 默认 0.0（确定性 judge）
```

缺任一环境变量抛 `RuntimeError`。

### 4.2 评审机制（`scoring.py`）

- **每条规则一个 `GEval`**（`scoring.py:_build_metrics`），`strict_mode=True` 强制二值 1/0、`threshold` 强制为 1，故每个 metric 的 `success` 即 pass/fail。
- `criteria` 字段 = 该规则的 `guidance`（PASS/FAIL 标准），不手写 prompt，复用 deepeval GEval 的基础能力。
- `evaluation_params`：默认只传 `ACTUAL_OUTPUT`（合同正文）；若给了 `task_desc` 则同时传 `INPUT`，让 judge 把起草需求作为上下文。
- **并发评审**：`ThreadPoolExecutor`（默认 `max_workers=8`，按规则数封顶）逐条 `metric.measure(test_case)`，镜像 harvey-labs 的并发模型；绕过 deepeval `evaluate()` test-runner（对 Ark 端点会超时）。
- **容错**：单条 judge 调用抛异常不致整跑失败，记入该条 `reasoning` 的 `[error: ...]`，verdict 视为 fail。
- 读取每个 GEval 实例上的 `success` / `reason` / `evaluation_model`（in-place 被 measure 改写）。

返回的 `judge_model` 取首个 metric 的 `evaluation_model`，回退到 `EVAL_MODEL` 环境变量。

---

## 5. 评估流程（`evaluate_contract`）

```
1. load_criteria(rubric_name)          # KeyError(未知 rubric) / ValueError(无规则)
2. judge = judge or get_judge()
3. test_case = LLMTestCase(input=task_desc, actual_output=contract_text)
4. metrics = _build_metrics(criteria, judge, include_input=bool(task_desc))
5. 并发 metric.measure(test_case)       # ThreadPoolExecutor
6. 聚合 criteria_results = [{id, title, verdict, reasoning}]
7. n_passed / all_pass / score / summary
8. return scores dict（harvey-labs scores.json 形状）
```

返回字段：`rubric, score, max_score, all_pass, n_criteria, n_passed, summary, criteria_results, judge_model, scored_at`。

`contract_evaluate` 工具（`tools/evaluate.py`）在此基础上：
- `contract` 入参既可是文件路径（存在则读文件）也可是内联正文（否则当文本）。
- `no_store=False` 时调 `store_result` 落库，返回值附 `run_id`。

---

## 6. 持久化

### 6.1 表结构（`store.py`）

**`eval_runs`** — 一次评估一行（运行级）：

```
id, rubric_name, contract_path, task_desc, score, max_score, all_pass,
n_criteria, n_passed, summary, judge_model, scored_at, created_at,
compare_run_id, prompt_name, prompt_type, variant_label, draft_text
```

**`eval_criteria_results`** — 每条规则判定一行（`run_id` 外键，`UNIQUE(run_id, criterion_id)`）：

```
id, run_id, criterion_id, title, verdict, reasoning, ordinal
```

**`compare_runs`** — 一次对比一行（分组键）：

```
id, label, contract_type, rubric_name, task_desc, gen_mode, n_drafts, created_at
```

### 6.2 快照语义

`store_result`（`store.py:274`）把 rubric 名、合同、`task_desc` 以文本快照写入，**评估记录不随后续 rubric 编辑/删除而失效**。compare 驱动的列（`compare_run_id` / `prompt_name` / `prompt_type` / `variant_label` / `draft_text`）为可选 kwarg：独立评估留空，对比评估填上以便分组与溯源（无外键）。

### 6.3 读取

- `run_list(limit)` — 近期运行（运行级字段）。
- `run_get(run_id)` — 单次运行 + 有序 `criteria_results`。
- `list_runs` / `get_run` 在 MCP 层即 `run_list` / `run_get` 工具。

`ensure_schema` 幂等建表 + 迁移加性列，按 dbname 记忆化，后续每次调用是廉价 no-op。

---

## 7. Compare 体系（prompt 横向对比）

`compare_run` / `run_compare`（`compare.py:87`）固定「区域」、只变 prompt，回答「哪个起草 prompt 更好」。

### 7.1 区域固定，prompt 唯一变量

固定：`contract_type` + `rubric_name` + `task_desc`（起草需求，也作 judge input）。变化：`prompt_names`（≥2）。每个 prompt 生成 `n_drafts` 份草稿，逐份评审。

### 7.2 drafter-only 生成

对比走 **drafter-only 模式**：每个草稿是**一次直接的 `DRAFTER` 模型 LLM 调用**（prompt 的 `content` 作 system 指令，`task_desc` + 模板参考块作 user 消息），**不调用生产 crew**。这样对比的是 prompt 本身的起草质量，而非 crew 的多步加工。`mode` 仅支持 `"drafter-only"`，`n_drafts < 1` 或 `< 2` 个 prompt 报错；rubric 未知/空时 fail-fast，不浪费 LLM 调用。

### 7.3 持久化与分组

`store_compare` 先建一行 `compare_runs`（label 缺省 `"{type} · {rubric} · {n} prompts"`），拿到 `compare_id`；每个草稿评审后 `store_result(..., compare_run_id=compare_id, prompt_name, prompt_type, variant_label, draft_text)`，归到该 compare 下。`draft_text` 入库以便复现，但 `get_compare` 默认不返回（体积大），用 `run_draft` 懒取。

### 7.4 矩阵聚合（`build_matrix`）

`compare_matrix` 把一个 compare 聚合成 **规则 × prompt** 矩阵：

- 行（criteria）：取首个有判定的 run 的 `criteria_results`（所有 run 共用同一 rubric，行一致）。
- 列（prompts）：按首次出现顺序。
- 单元格：
  - `n_drafts == 1`：`{verdict: pass/fail, reasoning}`（二值）。
  - `n_drafts > 1`：`{pass_rate: k/N, n_pass, n, reasoning}`（通过率，降低单次随机性）。
- `reasoning` 取首个可用，让视图不用额外请求就能显示「为什么」。

返回 `{criteria, columns, cells, n_drafts}`。

> 成本提示：`compare_run` 每个草稿 = 1 次 draft LLM + 1 次 judge（judge 内部每条规则一次调用），是昂贵工具。

---

## 8. 评估在自愈流水线中的角色

`pipeline_run`（`pipeline/graph.py`）的评估相关节点：

| 节点 | 作用 | 代码 |
|---|---|---|
| `evaluate` | 调 `contract_evaluate(filled_text, rubric, task_desc)` 评审已填槽合同 | `graph.py:143` |
| `check` | 按 `(n_passed, score)` 排序，保留历史最佳迭代 | `graph.py:154` |
| `_route` | `all_pass` 或达 `max_iterations` -> `store`；否则 -> `improve` | `graph.py:172` |
| `improve` | 用**失败规则**驱动 LLM 诊断，排除「瘦」custom 条款 | `graph.py:178` |
| `store` | 把**最佳迭代**写入 `pipeline_runs`，关联 `eval_run_id` | `graph.py:213` |

关键点：
- **排序键是 `(n_passed, score)`**（`graph.py:_rank`）。因 `score` 是 all-pass 二值，`n_passed` 才是区分多轮迭代优劣的主信号——`improve` 的目标是把 `n_passed` 推到 `n_criteria`。
- `improve` 的输入是 `eval_result.criteria_results` 中 `verdict != "pass"` 的失败项（`graph.py:181`），诊断后产出「排除哪些 custom 条款让富 base 接管」与「建议 reject 哪些条款供人复核」，**不改共享条款表**。
- `pipeline_runs` 行记录 `score / max_score / n_passed / n_criteria / all_pass / iteration / actions_taken / recommendations`，并通过 `eval_run_id` 关联到 `eval_runs` 的逐条判定。

---

## 9. 对外接口

### 9.1 MCP 工具

| 工具 | tag | 作用 |
|---|---|---|
| `contract_evaluate` | contracts | 评一份合同（文件路径或内联文本），返回评分 + 逐条判定，可选落库 |
| `rubric_list` | rubrics | 列 rubric（可选带规则数与 is_harbor） |
| `rubric_get` | rubrics | 取一个 rubric 的元数据 + 有序规则 |
| `rubric_create/update/delete` | rubrics | local rubric 增改删 |
| `criterion_add/update/delete/reorder` | rubrics | 规则级增改删与重排 |
| `run_list` / `run_get` | eval | 评估运行列表 / 单运行 + 逐条判定 |
| `compare_run` | eval | 多 prompt 起草+评审+分组落库 |
| `compare_list` / `compare_get` | eval | 对比列表 / 单对比分组结果（不含 draft_text） |
| `compare_matrix` | eval | 规则 × prompt 矩阵 |
| `run_draft` | eval | 懒取某 run 的 draft_text |
| `pipeline_run` / `pipeline_list` / `pipeline_get` | pipeline | 含评估的自愈流水线 |

### 9.2 REST API

评估的**执行**类操作（评一份合同、跑对比、rubric CRUD）目前仅通过 MCP 工具暴露，HTTP 层（`fd-coding-law-bench-mcp/.../api/routes/` 与主仓 `src/web/routes/`）未实现 `POST /eval`、`GET /rubrics` 等端点。

评估结果的**只读聚合**有 HTTP 入口：主仓 `src/web/routes/dashboard.py` 提供

- `GET /dashboard` - 评估看板页面
- `GET /api/dashboard/stats` - JSON 聚合统计：`pipeline_runs` 的总运行数、`all_pass` 数、平均通过率 `avg(n_passed/n_criteria)`、按 `contract_type` 取通过率最高的一行（`pass_pct`）

即：经 MCP 工具跑评估 -> 落 `pipeline_runs` / `eval_runs` -> dashboard HTTP 端点只读展示。

---

## 10. 数据模型总览

| 表 | 粒度 | 关键字段 | 所属 |
|---|---|---|---|
| `rubrics` | 一个规则集 | `name, context, source, description` | rubric 定义（`src/eval/rubric_crud`） |
| `criteria` | 一条规则 | `rubric_id, name, description, guidance, ordinal` | rubric 定义 |
| `eval_runs` | 一次评估 | `rubric_name, score, all_pass, n_passed, n_criteria, compare_run_id, prompt_name, draft_text` | `src/eval/store` |
| `eval_criteria_results` | 一条规则判定 | `run_id, criterion_id, verdict, reasoning, ordinal` | `src/eval/store` |
| `compare_runs` | 一次对比 | `contract_type, rubric_name, task_desc, gen_mode, n_drafts` | `src/eval/store` |
| `pipeline_runs` | 一次流水线 | `eval_run_id, score, n_passed, n_criteria, all_pass, iteration, actions_taken, recommendations` | `src/eval/pipeline_store` |
| `prompts` | 一个起草 prompt | `name, content, contract_type, prompt_type` | `src/eval/prompt_crud` |

---

## 11. 已知限制

- **Judge 结构性不可靠**：当前 judge（`EVAL_MODEL`）存在结构性误读——混淆「合同正文」与「评分项」、在合同里索要 PASS/FAIL 标记、误读字段。这会压低评估分上限，单次评分波动大。**不宜追逐单次分数**，也不应在分节已齐全后继续堆内容；多轮迭代看 `n_passed` 趋势与 `compare_matrix` 通过率更可信。
- **all-pass 放大噪声**：9/10 与 0/10 同为 0.0 分，单条规则的误判即可把整份合同压到 0 分。`n_passed` 是更稳的相对信号。
- **harbor rubric 与合同无关**：库内 2 条 harbor rubric（`task_quality` / `trial_behavior`）不用于合同评估，`contract_evaluate` 应传 `contract_<type>_v<N>`。
- **`draft_text` 体积**：对比场景下 `draft_text` 入库但默认不返回，需显式 `run_draft` 懒取。
- **drafter-only 对比**：`compare_run` 只比 prompt 的单次起草质量，不含生产 crew 的多步加工，故对比结论不等于生产管线表现。
