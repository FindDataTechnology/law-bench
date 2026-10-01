# 合同生成逻辑说明

本文档系统说明一份合同从「合同类型 + 标签」到「可填充、可评估、可交付的合同文本」的完整生成逻辑，覆盖装配算法、槽位系统、一致性校验、LLM 填槽、自愈流水线与对外接口。

> 核心装配代码位于 `src/clauses/assemble.py`；槽位模型在 `src/contracts/slots.py`、`src/contracts/slot_ontology.py`；MCP 工具与 REST API 在 `fd-coding-law-bench-mcp/`。

---

## 1. 总览

系统有三条执行路径，共用同一套装配内核：

```
                          ┌─────────────────────────────────────┐
  contract_generate       │  路径 A：母版骨架                    │
  (无 stance/scenario) ──►│  generate_contract()                │
                          │  渲染 contracts.json 里的模板正文     │
                          └─────────────────────────────────────┘

                          ┌─────────────────────────────────────┐
  contract_content        │  路径 B：Tag 驱动装配（主路径）       │
  contract_generate       │  generate_contract_assembled()      │
  (带 stance/scenario) ──►│  base+tagged+custom 分节覆盖 →       │
                          │  一致性校验 → 渲染                    │
                          └─────────────────────────────────────┘

                          ┌─────────────────────────────────────┐
  pipeline_run            │  路径 C：自愈流水线                   │
  ──────────────────────► │  generate→fill→evaluate→check→      │
                          │  (improve)→store  LangGraph          │
                          └─────────────────────────────────────┘
```

- **路径 A**：无标签时，直接渲染 `contracts.json` 中该类型的母版模板（骨架），返回带 `{{slot}}` 占位符的正文。
- **路径 B**：传入 `stance` 和/或 `scenario` 时，从条款库按分节覆盖规则装配一份合同。**这是生产主路径**，`contract_content` 恒走此路径。
- **路径 C**：在路径 B 之上叠加 LLM 填槽 + 评估 + 自愈循环，产出已填值、已评分的合同并落库。

---

## 2. 核心概念

| 概念 | 说明 |
|---|---|
| `contract_type` | 合同类目 key，如 `sale` / `lease` / `employment`，共 43 类。母版模板存于 `src/contracts/data/contracts.json`。 |
| `scenario` | 业务场景标签（如 `农产品买卖`、`驾校培训`、`住宅租赁`），用于筛选 **tagged** 条款。 |
| `stance` | 立场标签（`pro_a` / `pro_b` / `balanced`），用于筛选 **custom** 条款。 |
| **clauses 三层** | `base`（母版骨架，10 个规范分节）/ `tagged`（场景覆盖与扩展）/ `custom`（立场覆盖）。 |
| **slot** | 正文中的 `{{slot}}` 占位符，如 `{{party_a}}`、`{{amount}}`。每个槽位有一份「填充说明」（label/description/example/required）。 |
| `tag_review` | 条款逐维审批状态（`pending`/`approved`/`rejected`）。custom 条款仅当**所有维度均为 `approved`** 时 `is_assembly_ready` 才为真，方可参与装配。 |

> 注意：`region` / `province` 已弃用，省份是来源信息而非法律轴；真正的条款变异轴是 `scenario`（业务场景）。`tags` 中只识别 `stance` 与 `scenario`，其余 key 被忽略。

---

## 3. 生成路径

### 3.1 母版骨架路径（路径 A）

入口：`src.contracts.generate_contract(contract_type, format, out_dir)`。

无 `stance`/`scenario` 时由 `contract_generate` 工具触发（`tools/generate.py:83`）。直接读取 `contracts.json` 里该类型的 `body`（含 12 个规范 `{{slot}}`），渲染为 docx/pdf。返回值带 `laws`（非 `law_refs`）。这条路径不查条款库、不做分节覆盖。

### 3.2 Tag 驱动装配路径（路径 B，主路径）

入口：`src.clauses.assemble.generate_contract_assembled(contract_type, scenario=, stance=, format=, custom_clause_ids=)`（`assemble.py:206`）。

- `contract_content` 工具恒走此路径（`tools/content.py:71`）。
- `contract_generate` 在传入 `stance` 或 `scenario` 时切到此路径（`tools/generate.py:73`）。
- `pipeline_run` 的 `generate` 节点也调用此路径（`pipeline/graph.py:106`）。

返回：`{docx_path, pdf_path, body_text, slots, instructions, law_refs, diagnostics}`（`assemble.py:273`）。`format="markdown"` 时不做文件 I/O，最快返回。

---

## 4. 装配算法（`generate_contract_assembled`）

### 4.1 条款收集（`_select_clauses`，`assemble.py:105`）

```
base   = list_clauses(type, category="base")                    # 恒全量
tagged = list_clauses(type, category="tagged", tags={"scenario": scenario})  # 按场景筛
custom = ── custom_clause_ids 显式指定 ── 或 ──
         list_clauses(type, category="custom", tags={"stance": stance})
         再过滤 is_assembly_ready(c) == True                    # 按立场筛 + 必须审批就绪
```

- `custom_clause_ids` 用于自愈循环**按次运行**排除某些 custom 条款，而**不改动共享条款表**。
- `scenario` 为空则不带 tagged；`stance` 为空则不带 custom。

### 4.2 分节覆盖（`_resolve_sections`，`assemble.py:75`）

**每个分节只渲染一条条款正文，不堆叠拼接。** 覆盖优先级：

```
resolved section = custom(stance)  ─┐
                > tagged(scenario) ─┤  首个命中者胜出
                > base(母版)       ─┘  base 永远兜底
```

按 `section` 分组后，依 `custom → tagged → base` 顺序取第一个非空源。母版未定义的 section（扩展节）插在 `附则` 之前。

### 4.3 同源 tiebreak（`_pick_variant`，`assemble.py:56`）

同一源内多条条款命中同一 section 时，按以下键取最小者：

```
manual=true  >  {{slot}} 数量多  >  正文长  >  id 小
```

经此 tiebreak 解决的 section 记入 `diagnostics.heuristic_sections`（干净数据下为空列表）。

### 4.4 正文组装（`_assemble_body`，`assemble.py:141`）

```
## {section}

{clause.body}

（按规范分节排序，节间空行分隔，不拼接）
```

### 4.5 排序

`_section_sort_key`（`assemble.py:69`）：规范 section 按 `SECTION_ORDER` 固定序；非规范（扩展）节统一排在 `附则` 之前。

---

## 5. 槽位系统

### 5.1 规范槽位（`src/contracts/slots.py`）

12 个 `REQUIRED_SLOTS`，单点真源，模板骨架与类型化模板共用：

```
party_a, party_b, subject, amount, term_start, term_end,
party_a_duty, party_b_duty, penalty, jurisdiction, sign_date, sign_location
```

`default_slot_instructions(zh)` 为这 12 个槽返回默认填充说明（`subject` 示例按合同类型定制，`slots.py:69`）。

扩展概念在 `src/contracts/slot_ontology.py`（`address`、`phone`、`agent`、`legal_rep`、`bank`、`account`、`delivery_date`…），带别名与角色前缀映射（如 `sale` 下 `seller_address → party_a_address`，`lease` 下 `lessor_address → party_a_address`）。

### 5.2 `slots` 字段

```python
slots = list(dict.fromkeys(SLOT_PATTERN.findall(body)))   # assemble.py:245
```

`SLOT_PATTERN = \{\{\s*([a-zA-Z_][\w-]*)\s*\}\}`（`src/docs/slots.py:34`）。

**`slots` = 装配后 `body_text` 中实际出现的 `{{slot}}` 名，按首次出现去重保序。** 它是「这份合同正文里有哪些槽」的完整集合，但**不保证**等于该类型的 12 个规范槽——若某覆盖条款删掉了某个规范占位符，该槽不会出现在 `slots`。

### 5.3 `instructions` 字段（`_build_instructions`，`assemble.py:151`）

三源并集，按 `name` 去重：

```
1. 12 个规范默认说明            （恒包含，与正文无关）
2. 各条款自带的 slot_instructions
3. 本体回退：正文中出现但仍无说明的槽 → instruction_for_slot(slot, type)
```

因此 `instructions` **是 `slots` 的超集**：恒含 12 个规范槽，且覆盖正文中所有槽。一致性校验保证「正文每个槽都有说明」（见第 6 节），所以一旦装配成功返回，`body_text` 里的每个槽都可在 `instructions` 中找到填充指引。

> 对外接口的角度：`contract_content` / `contract_generate` / `contract_generate_batch` 都返回 `slots` + `instructions` + `law_refs`；`contract_type_catalog` / `type_metadata` 只返回 `slot_count`（整数）；tag 类工具不返回任何槽信息。

### 5.4 写入时归一化

条款入库时（`store._row`），正文与 `slot_instructions` 中的槽名被归一化到规范名（如 `seller_address → party_a_address`），`body_hash` 由归一化后正文重新派生。未知且仅出现一次的槽保留原样；若它缺说明，一致性校验会标记为数据债。

---

## 6. 一致性校验（coherence gate，`src/clauses/coherence.py`）

渲染前强制校验，失败抛 `CoherenceError`（作为 MCP 工具错误上抛，不写文件）：

```
(a) 母版定义的每个 section 都已在装配结果中存在
(b) 无重复 section
(c) body 中每个 {{slot}} 都有对应 instruction     # body_slots ⊆ instr_names
```

其中 (c) 由 `uninstr = body_slots - instr_names` 计算（`coherence.py:59-62`），非空即报错。注意校验是单向的：只要求「正文槽都有说明」，不要求「说明都对应正文槽」，所以 `instructions` 可以包含正文未使用的规范槽。

---

## 7. 渲染

`generate_contract_assembled` 依 `format` 参数渲染（`assemble.py:252-271`）：

| format | 行为 |
|---|---|
| `markdown` | 不做文件 I/O，仅返回 `body_text`，最快 |
| `docx` | `create_docx(body, path, title=zh)` 写一份 docx |
| `pdf` | 先生成临时 docx，再 `docx_to_pdf` |
| `both` | 同时写 docx + pdf |

每个 `{{slot}}` 渲染为高亮可填占位符。输出目录默认 `output/contracts`，文件名 `{type}__{scenario}.{ext}`（无 scenario 则 `{type}.{ext}`）。

---

## 8. LLM 填槽（`pipeline/fill.py`）

`fill_slots`（`fill.py:94`）用 `DRAFTER_MODEL`（litellm）为**每个** `{{slot}}` 生成场景感知的具体值：

- **Prompt**（`fill.py:43`）：把 `instructions` 列成清单，要求输出严格 JSON `{"槽名": "值"}`；`task_desc`（起草需求）会注入，使 `subject` 等槽值贴合需求（如指定了标的就用指定标的）。
- **缓存**：`fill_cache` 表按 `(contract_type, scenario, sorted(slots), model, temperature, task_desc)` 的 sha1 键 memoize（`fill.py:30`）。命中即跳过 LLM；`temperature` 默认 0 以保证可复现。
- **过滤**：只保留 LLM 输出中属于 `slots` 的键（`fill.py:122`）。
- **回填**：`render_filled`（`fill.py:127`）用 `SLOT_PATTERN.sub` 把 `{{slot}}` 替换为值；值为空则保留占位符并计入 `unfilled_slots`。

---

## 9. 自愈流水线（`pipeline/graph.py`，`pipeline_run` 工具）

LangGraph 状态机：`generate → fill → evaluate → check → (improve) → store`。

```
START → generate → fill → evaluate → check ─┬─ all_pass 或 达 max_iterations ─→ store → END
                                             └─ 否则 ─→ improve → generate(回到开头)
```

### 9.1 节点

| 节点 | 作用 | 代码 |
|---|---|---|
| `generate` | 调 `contract_generate(format="docx")`，取 `body_text/slots/instructions` | `graph.py:103` |
| `fill` | LLM 填槽 + 回填，得 `filled_text`、`unfilled_slots` | `graph.py:121` |
| `evaluate` | 调 `contract_evaluate(filled_text, rubric, task_desc)` 评分 | `graph.py:143` |
| `check` | 按 `(n_passed, score)` 排序，保留历史最佳迭代 | `graph.py:154` |
| `_route` | `all_pass` 或迭代达上限 → `store`；否则 → `improve` | `graph.py:172` |
| `improve` | LLM 诊断失败项，排除「瘦」custom 条款，记录建议 | `graph.py:178` |
| `store` | 把**最佳迭代**写入 `pipeline_runs`，关联 `eval_runs` | `graph.py:213` |

`rubric` 缺省时取该类型最高版本（`contract_<type>_v<N>`，`graph.py:69`）。`max_iterations` 默认 3，置 1 关闭自愈。

### 9.2 `improve` 的安全设计（`pipeline/improve.py`）

针对评估未全通过的情况，LLM 诊断后产出两类动作：

- **`exclude_custom_clause_ids`**：本轮通过 `custom_clause_ids` 排除的 custom 条款 id（让富 base 接管该 section）。**按次运行生效，不改共享条款表**。
- **`recommendations`**：建议全局 reject 的 `clause_review` 动作，仅记录在 pipeline 行上**供人复核**，**循环绝不自动执行**。

鲁棒性：任何 LLM/解析失败都返回空动作，循环不崩溃，仅继续重跑至 `max_iterations`（`improve.py:104-109`）。`diagnose` 在无失败项或无 custom 条款时直接返回空。

### 9.3 落库

`store_node` 把最佳迭代的 `filled_text`、`fill_values`、`eval_run_id`、`score`、`actions_taken`、`recommendations`、`fill_temperature` 写入 `pipeline_runs`（`graph.py:213`）。`pipeline_list` / `pipeline_get` 可读回，`pipeline_get` 额外附上关联 eval 的逐条 `criteria_results`。

---

## 10. 对外接口

### 10.1 MCP 工具

| 工具 | 路径 | 返回槽信息？ |
|---|---|---|
| `contract_type_catalog` | catalog | 仅 `slot_count`（int） |
| `type_metadata` | catalog | 仅 `slot_count`（int） |
| `contract_content` | content | `slots` + `instructions` + `law_refs`（恒走装配路径） |
| `contract_generate` | generate | 无标签→骨架（`laws`）；有标签→装配（`slots`+`instructions`+`law_refs`） |
| `contract_generate_batch` | batch | 每项 `slots` + `instructions` + `law_refs` |
| `clause_list` / `clause_get` | clauses | 每条款的 `slot_instructions` + `law_refs` |
| `pipeline_run` | pipeline | `pipeline_run_id`、`score`、`actions_taken`、`recommendations` 等 |
| `tag_vocab_list` / `tag_validate` / `tag_combinations_list` | tags | 无（标签维度工具，与槽正交） |

### 10.2 REST API（FastAPI，`fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/api/routes/`）

| 方法 | 路径 | 包装的工具 |
|---|---|---|
| `POST` | `/contracts/content` | `contract_content` |
| `POST` | `/contracts/batch` | `contract_generate_batch` |
| `GET` | `/contracts/types` | `contract_type_catalog` |
| `GET` | `/contracts/types/{type}` | `type_metadata` |
| `GET` | `/tags/combinations/{type}` | `tag_combinations_list` |
| `POST` | `/tags/validate` | `tag_validate` |

REST 用 Pydantic `response_model` 校验：`ContractContentResponse` 与 `ContractBatchItem` 显式声明 `slots`/`instructions`/`law_refs`，故这些字段不会被过滤掉（`api/schemas.py:41-49, 99-101`）；catalog/metadata 响应仅含 `slot_count`。

> **接口缺口**：没有只读端点直接返回某类型的完整槽位清单（规范槽名 + 填充说明）而不装配合同。`get_template(type)["slots"]` 与 `get_slot_instructions(type)` 仅在库层可用，未暴露为 MCP/HTTP。要枚举槽位，目前只能调 `contract_content(format="markdown")` 读 `instructions`，或调 `clause_list` 收集各条款 `slot_instructions`。

---

## 11. 数据模型（关键字段）

**`clauses` 表**：`id, contract_type, section, body, tags(source/scenario/stance/...), tag_review, slot_instructions, law_refs, body_hash, manual, source_doc_title`。`tags.source` 区分 `base`/`tagged`/`custom`。

**`fill_cache` 表**：`cache_key, contract_type, scenario, slots_hash, fill_values, temperature, model`。键见第 8 节。

**`pipeline_runs` 表**：`contract_type, tags, stance, rubric_name, task_desc, fill_mode, fill_values, filled_text, eval_run_id, score, max_score, n_passed, n_criteria, all_pass, iteration, actions_taken, recommendations, fill_cache_id, fill_temperature, created_at`。

**`eval_runs` 表**：`contract_evaluate` 的逐条 `criteria_results`，被 `pipeline_runs.eval_run_id` 关联。

---

## 12. 已知限制

- **母版缺失类型**：`capital_increase` 的 `base=0`，装配出空合同。
- **curation 待铺开**：`sale` 是已完成清理的试点；其余约 41 个类型尚需 base 清洗 + tagged 去重 + custom 审批的清理流程（见 `docs/tag-driven-assembly.md` 的 playbook）。
- **custom 审批**：跨类型 custom 条款需要真实人工 `tag_review`，而非试点期的自动 approve。
- **槽位长尾**：本体未覆盖约 5184 个仅出现一次的槽。
- **`law_refs` 去重**：仅按精确名称去重，「中华人民共和国民法典」与「民法典」算两条。
- **judge 上限**：评估 judge（`kmodel_latest`）存在结构性误读（混淆合同与评分项、在合同里索要 PASS/FAIL），会压低评估分上限；单次评分波动大，不宜追逐单次分数。
