## Context

见 proposal.md。当前状态的关键事实：内核写入面（`src/bench/authoring.py` 的
`authoring_create_unit / update_unit / delete_unit / create_relationship /
delete_relationship`）已具备词表闸与 append-only `authoring_events`；提案层
（`src/bench/proposals.py`）已规定「本体写入只能走内核，本模块不含
`INSERT INTO knowledge_units`」。缺的是人机接口。

`knowledge_units` 的形状：`(kind, namespace, external_key)` 唯一，`namespace` =
域 key（域化后），软删用 `tags->>'deleted'`（`ledger.curation_layer` 已按此计
`deleted` 子集），关系把端点存在 `attrs.from/to/from_key/to_key`。

## Goals / Non-Goals

**Goals**

- 单条与批量的写入**同一个校验器**，未通过就不落库。
- 批量导入支持部分成功，并逐行回报；同一份内容重复导入是更新而非新增。
- 删除是软删（可恢复），且必须留痕。
- 一眼能看出「模板声明了但没整理」与「这些是测试数据」。

**Non-Goals**

- 不做图谱可视化（本轮只做列表与端点选择；图渲染要单独的布局/交互设计）。
- 不自动抽取（从 364,916 块语料里 LLM 抽候选是另一个大变更）。
- 不改 `knowledge_units` schema，不引入新的写路径。
- 不做冲突合并（同一 key 的并发编辑按「后写覆盖 + 留痕」处理，不做三方合并）。

## Decisions

**D1 一个校验器，两个模式。** `plan_import(conn, domain, payload) -> list[Row]`
逐行产出 `{action: create|update|skip|error, reason, payload}`；`apply_plan()`
只消费这份计划、逐行调内核。干运行与落库都调 `plan_import`，因此不可能出现
「预判通过、落库失败」的静默差异——差异只可能来自两次调用之间数据变了，此时
落库会把该行如实报成 error 而不是沉默。
- 备选：干运行用一套轻校验、落库再全校验 —— 会让预判变成装饰品，否掉。

**D2 逐行走内核，不做大事务。** 内核每行自己提交并写事件。批量语义是「部分成功」，
包成一个大事务反而要求全有或全无，与需求冲突。代价：中途失败会留下已写入的行，
所以返回值必须逐行标注。

**D3 关系端点用 external_key 引用，在预判时解析成真实实体。** 导入内容里
`from_key`/`to_key` 指实体的 external_key；预判阶段查本域未软删实体，找不到即
该行 error。端点不允许是自由文本——与页面选择器同一套解析。
- 备选：让用户填 `kind:key` 复合串 —— 多一个语法层，错误信息更难读，否掉。

**D4 软删沿用 `tags.deleted`，不加列。** 与 `ledger.curation_layer` 现有的
`tags->>'deleted' = 'true'` 统计口径一致；恢复 = 把该键去掉。不加 `deleted_at`
列，避免与本轮「无 schema 变更」的边界冲突。

**D5 测试数据只标注、绝不自动删。** 判定用显式特征（external_key 以 `smoke`
开头，或 body/attrs 含「冒烟」）。页面给一个折叠区列出它们并提示清理；删除仍
需要人点。理由：误判真实数据为测试数据比漏标危险得多。

**D6 角色用既有 capability 位。** 写=`cap.can_write`（expert+），删除=
`cap.can_assign`（lead+），读=`cap.can_read`。不新增角色语义。

**D7 列表筛选走新增只读查询。** `authoring_list_units` 已存在；需要补的是
「按 kind / 关键词 / 是否含已删」的过滤与分页，放在 authoring（读）里，避免页面
自己拼 SQL。

## Risks / Trade-offs

- **批量导入把错误的词表写进库**：靠 D1 的同一校验器 + 内核自身的词表闸双重拦。
- **软删的实体仍被关系引用**：页面在实体详情里列出引用它的关系；删除时提示
  「有 N 条关系引用」。不级联删除（级联会静默扩大影响面）。
- **事件流膨胀**：每次写入一条事件，导入 100 行就是 100 条。可接受——这正是
  审计要的粒度；页面只默认展示最近 N 条。
- **生产现有 11 条冒烟单位**：本变更只提供识别与删除能力，清不清由人决定
  （proposal「Impact」已注明）。
