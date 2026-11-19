# 设计：词表外 kind 的预检

## D1 为什么不是「加进现有两类」，而是新设异常类型

`_lane_for_kind` 现在一个 `ValueError` 盖住四种情形：

| 情形 | 正解 |
| --- | --- |
| 域锚定的 `template_id` 不存在 | 修域/模板数据 |
| 模板 `schema` 不是 dict | 修模板数据 |
| 两张词表都空或缺失 | 判不出（这个域可能就不用词表） |
| `kind` 不在任一张非空词表里 | **拒提交方**（确定落不下去） |

预检原本一句 `except ValueError: return` 把四种一起放过。若直接把 `except ValueError`
改成「一律拒」，前三种就变成**拒提交方来修服务端数据**——那是假红，比假绿更坏：
它会教舰队停止提交正当内容（上一笔变更 design 里已写下的判据）。

所以新设 `class KindNotInVocabulary(ValueError)`，**只**在第四种抛。选子类的三个理由：

1. **零行为变更**：确认路径（`_write_through_kernel`）与所有既有 `except ValueError` 调用方
   捕到的仍是同一个东西，逐字不变。
2. **可判别的意图**：读代码的人一眼看出「这个 ValueError 是词表裁决，不是数据坏了」。
3. **判据只有一份**：词表的权威仍在 `_lane_for_kind`，预检不自己再读一次模板——两次读会
   分叉（假红/假绿的来源）。

## D2 「空词表」不必单列（我曾为它留过一条臂，后来撤了）

第一版设计里，「两张词表都空」被我当成需要放行的一档，理由是「判不出 ⇒ 不许算到提交方账上」。
写用例时才发现这是个**造不出来的状态**：

- `templates.REQUIRED_SCHEMA_KEYS` 要求 `entity_types` / `relationship_kinds` 必须存在；
- `_LIST_KEYS` 校验要求它们**非空**（`not value` 即报「must be a non-empty list」）；
- 生产实测 5 个模板（legal v1/v2、gov v1/v2、data-ontology v1）两张表全部非空。

也就是说 API 面上不存在「没有词表的模板」。用 SQL 硬插一行去造它，测的是系统产生不出来的
状态——那是夹具在替我说话，不是判据。所以撤掉那条臂与对应 scenario，代码里也不为它留分支：
真从旧数据里冒出来时**拒绝是对的**（确认走同一张表，照样抛），多留一个「放行」分支反而是
一条永不执行的路径。

真正需要区分的只有两种，而它们都可达、都在代码里：

| 情形 | 可达吗 | 抛什么 |
| --- | --- | --- |
| 域锚定的模板 id 指向不存在的模板 | 是（删模板/脏数据） | 裸 `ValueError` ⇒ 预检放行 |
| 模板 `schema` 不是 dict | 是（旧数据） | 裸 `ValueError` ⇒ 预检放行 |
| `kind` 不在两张词表里 | 是（生产 3 条 `n:1`） | `KindNotInVocabulary` ⇒ 拒绝 |

## D3 三面同口径（其中抽取面这一桶结构上不可达，要写明）

| 面 | 表现 |
| --- | --- |
| 机器面（`/distribution`） | 409，`detail {reason: "kind_not_in_vocabulary", message, hint}` |
| 会话面（console） | 同一个 409、同一个理由词（复用 `ProposalTargetExists`，路由不改） |
| 抽取流水线 | 桶 `skipped.kind_not_in_vocabulary`（**通常恒为 0**，理由见下） |

**修正一个我一开始写错的事实**：我原以为 `bad_kind` 判的是「包声明的词表」、与模板词表
可能分叉。读代码后发现不是——`extraction.py` 的两张词表取自 `tmpl["schema"]`
（`domain` → `get_template_by_id`），与 `_lane_for_kind` 读的是**同一张**；而且它在提交前就
用这张表预筛（`if kind not in vocab → bad_kind`）。所以：

- 抽取路径**永远不会**触发 `kind_not_in_vocabulary`；
- 这一类真正的人群是**直连提交方**（MCP / 控制台）——生产里 3 条 `n:1` 的 `source` 全是
  `fleet:…`，实证如此。

那个桶仍然要加，但理由换成一条工程理由：`except ProposalTargetExists` 分支现在是
`report["skipped"][exc.reason] += 1`，**预检每多一个理由词就多一次 KeyError 风险**，而
KeyError 会打断整批（几百行）。注释必须写明「恒为 0 是正常的」，否则读报告的人会把 0 读成
「这类问题不存在」——那正是「恒假判据」的味道。

## D4 顺序仍排在幂等去重之后

同一个键、同一来源、同一依据的重放必须仍返回既有提案与 `created=false`。预检只回答
「这条此刻落不落得下去」，不改幂等语义。本变更不动这条顺序。

## D5 hint 必须点名人的那条路

`kind_not_in_vocabulary` 的正当路径有两条，且**第二条只能人做**：

1. 改用词表内的 kind 重提（提交方自己做）；
2. 由域负责人扩模板词表（`templates` 是数据，扩词表是一次治理动作，不是 bug 修复）。

所以 hint 要同时给出模板版本与两张词表的内容——只说「kind 不合法」会让人以为是笔误。

## 风险

- **假红**：域模板词表声明不全（漏了某个本来合法的 kind）。代价是新提交被拒、提交方看到
  明确词表；相比之下让提案进箱、占住确认位、到确认才失败更贵。且 D2 已挡住「没声明词表」
  这一档。
- **不影响存量**：既有 pending 不动。
