# 词表外的 kind 也拒在提交口

## Why

上一笔 `refuse-unlandable-proposals` 在提交口拦了两类**确定性**落不下去的提案
（`key_already_live` / `endpoints_missing`），并刻意留下第三类不拦：

> 「`kind` 不在词表」同样是确定性落不下去，但加进预检会是在本变更声明的两类之外偷偷加
> 第三类。（该变更 tasks §7.2）

留下的理由是流程纪律（不许夹带），不是判据不清。现在这笔把它补成**显式声明**的第三类。

生产里的证据（2026-11-15/16 只读核对 `legal` 域，`kubectl --context cheap -n postgres
exec postgres-0 -- psql -U app -d law_bench`）：

- 14 条 pending 里有 **3 条** `kind='n:1'`（#86、#90、#94），而 legal 域锚定模板 v2 的两张
  词表是实体 `["clause","law","concept"]`、关系 `["cites_law","superseded_by",
  "belongs_to_contract_type","defines"]`——`n:1` **两头都不在**。它们是 11-11 那批探针草稿。
- 这 3 条的 `source` 全是 **`fleet:…`**，即**直连提交方**（MCP / 控制台），不是抽取流水线。
  这一条决定了修法落点：抽取侧在提交前已按同一张模板词表预筛
  （`extraction.py` 的 `bad_kind`，词表取自 `tmpl["schema"]`），**只有直连提交方**能把
  词表外的 kind 送进箱。
- 这类提案**永远确认不了**：确认走 `_write_through_kernel` → `_lane_for_kind`，同一把词表
  在那里抛 `ValueError`。所以它不是「也许能过」，是**确定过不了**。

危害不是数据损坏（确认会响亮失败），而是**占住评审队列**：负责人打开待确认列表，看到的是
永远确认不了的行；提交方从 409 之外得不到任何反馈，只会重提。

## What Changes

- **预检加第三类理由** `kind_not_in_vocabulary`：提交的 `kind` 在该域**锚定模板**的两张词表
  （`entity_types` / `relationship_kinds`）里都不存在 ⇒ 提交口当场拒，HTTP 409，
  `detail` 点名该 kind 与模板版本，`hint` 给出两条正当路径（改用词表内的 kind；或由域负责人
  扩模板词表——那是人的裁决，不是提交方能自己解的）。
- **区分「确定落不下去」与「判不出」**：`_lane_for_kind` 现在对四种情形抛同一个
  `ValueError`（模板 id 不存在、schema 不是 dict、两个词表都空、kind 不在词表）。前三种的
  正解是修数据，不是拒提交方 ⇒ 新设 `KindNotInVocabulary(ValueError)` **只**在第四种抛；
  子类化保证确认路径与所有既有 `except ValueError` 调用方行为逐字不变。
- **两面同口径**：机器面/会话面继续走同一条 `ProposalTargetExists` → 409 通道（无需改路由）；
  抽取流水线加一个桶 `kind_not_in_vocabulary`。**这个桶在抽取路径上结构不可达**（那一侧提交前
  已用同一张模板词表预筛成 `bad_kind`），加它的唯一理由是「预检新增理由词时不要让
  `report["skipped"][exc.reason]` 撞 KeyError 把整批打断」，注释里要写明这一点——否则下一个人
  会把常年的 0 读成「这类问题不存在」。

不动的东西：前两类的判据与顺序（预检仍在幂等去重之后）；语义类驳回仍归人；
确认路径的失败行为不变（`kind` 越界在确认时照样抛，只是新提交不再走到那里）。

## Impact

- Affected spec: `fleet-submitter-contract`（MODIFIED 一条 requirement，新增 1 个 Scenario）
- Affected code: `src/bench/proposals.py`（异常类型 + 预检分支 + docstring）、
  `src/bench/extraction.py`（一个桶）、测试
- 生产影响面：只影响**新提交**。既有 pending（`legal` #86/#88–#94、`data-ontology` 7 条未核）
  一行不动——它们已是既成事实，且本条只判「新提交」。
- 假红的两条边界（设计期逐条核过）：「模板 id 指向不存在的模板」「schema 不是 dict」这两类
  **判不出**的形态不进本类拒绝——正解是修服务端数据。而「模板没有声明词表」这一档并不存在：
  `validate_template_schema` 要求两个词表键必填且非空，生产 5 个模板实测全非空。
