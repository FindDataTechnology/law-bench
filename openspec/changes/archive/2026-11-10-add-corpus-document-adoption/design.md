# 设计：语料文档目录与取材

## 1. 为什么是「派生目录」而不是一张 `corpus_documents` 表

一张表要同步，同步就会漂移，而漂移在这里的代价是**人以错的清单做取材决定**。目录的唯一真源是存储本身（Qdrant payload / 外接表），每次按需派生：

- 结构：`documents(conn, library, source, offset, limit, q)` → `{rows, total, cursor, error?}`
- 不可达的库返回 `error`，**不返回空列表**（与 `library_index.count_scope` 同一条纪律：够不着 ≠ 没有）。
- 分页与总数来自存储侧（Qdrant `facet` / `count` 精确模式），不在应用侧抽样估算。

代价是每次浏览要打一次存储；收益是清单永远等于库。这个交换在本项目已有先例（知识柱计数就是直连存储）。

## 2. 来源自述文档结构（`ingest_rule.document`）

内核不许知道 `law_id`、`title`、`chunk_text` 这些域字段名——有 `test_kernel_domain_free` 闸。因此映射写在来源上：

```json
{"document": {"id": "law_id", "title": "title", "text": "chunk_text",
              "order": "chunk_no", "kind": "law_type",
              "doc_filter": {"match": {"category": ["法律", "宪法"]}}}}
```

- 缺 `document` 映射的来源在目录里**明确报「该来源未声明文档结构」**，不是静默跳过。
- `doc_filter` 用于把「来源」再细分（例如 `statutes` 里只要 `法律`），可缺省。
- 与 `columns` 映射（外接表）同一处、同一机制：**结构由数据侧的登记声明**，不是代码里的 if。

## 3. 取文档：一条 `law` 单位

- 键：`keys.fold(title)` 后的规范名（沿用 `packs/legal/entity_keys.py` 的归一规则；内核只调 registry）。
- `body`：标题 + 类别/类型/发布日/状态，**只写语料里有的字段**，缺字段不补。
- `attrs`：`{"corpus": {"library": ..., "source_key": ..., "law_id": ...}, "chunks": N, "publish": ..., "status": ...}`。
- 证据：`authoring_create_unit` 的 `attrs.evidence` 记该文档首个 `chunk_id` 与一段逐字引用（沿用抽取候选的证据形状，便于同一套复核习惯）。
- 幂等：同键已存在即回同一单位（内核既有行为），页面显示「已在本体」。

## 4. 取条款：确定性切分

输入：该文档的全部语料块（按 `order` 排序）。
输出：`[{no, key, text, from_chunk, truncated}]`。

规则：

1. 用 `keys.clause_no()` 认条款头（`第N条`），**只认条款**（章/节/序言不算，已有规则）。
2. 一个条款的正文 = 从它的条款头到下一个条款头（或文档结束）之间的原文，逐字保留。
3. 跨块：按 `order` 顺序拼接后再切；若某条款在已取到的块的末尾仍未闭合并还有后续块没取，标 `truncated=true` 并记录缺哪一段，**不猜**。
4. 一个条款都切不出（如「修改、废止的决定」类）→ 报 `clauses=0` 与原因（`no_clause_headers`），不造单位。
5. 上限：单次取用最多 `MAX_ADOPT_CLAUSES = 200` 条，超出报 `capped` 并给出剩余数，由人再点一次。

写路径：每条经 `authoring_create_unit(kind="clause", external_key="<law_key>#<N>", body=<原文>, attrs={law_key, clause_no, chunk_id, truncated})`。批量写在一个事务里，任一条被内核拒（词表/键规则）→ 整批回滚并报出被拒的那条，不写一半。

## 5. 界面

`/d/{key}/library`：

- 左：来源列表（带块数），中：文档表格（标题/类别/状态/块数/是否已在本体），上：搜索与分页。
- 行操作：「取入本体」（law）、展开后「取条款」（≤200）。
- 已在本体的文档标 `已取入` 且条款按钮可用；重复取只更新不新建（幂等由内核保证）。
- 空态与错误态分开：库不可达 → 红色错误条 + 存储原话；库里确实没有该来源的文档 → 空态。

## 6. 不做

- 不做后台全量灌库：34,010 份文档一次全进本体 = 把语料表复制成第二份本体，失去策展含义。
- 不做自动选材（按热度/引用次数推荐）：语料里没有可靠信号，编一个排序等于编造优先级。
- 不改检索：检索仍然走 `library_index`，目录只是取景框。
