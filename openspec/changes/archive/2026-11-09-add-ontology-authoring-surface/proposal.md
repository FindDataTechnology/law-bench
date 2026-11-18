## Why

法律域现在有 364,916 块法规语料、11 条知识单元，而这 11 条里 **5 个「实体」是冒烟测试留下的**（`冒烟日期`/`冒烟订单`/`冒烟客户`/`冒烟桥表`/`冒烟订单×冒烟客户 连接`）——真正被整理进本体的内容为零。原因是写入面不存在：`/d/{key}/ontology` 是纯只读台账，内核 `authoring_create_unit/relationship` 与提案层都在，但**没有任何界面能建一个实体或连一条关系**，只能靠脚本或走「提案 + 证据」那套评审流。

用户接下来要「快速填充很多细分领域的 ontology」——每个新域都要先把自己那套实体/关系立起来。没有编辑与批量导入，这一步的成本就是「每次找人写脚本」，域树建得再快也长不出内容。

## What Changes

- `/d/{domain}/ontology` 从只读台账扩成「可编辑台账」：新增单位列表（按 kind/层级/关键词筛选、含软删标记）、实体与关系的创建/编辑/删除表单，全部经内核 `authoring_*`（词表闸 + 追加式事件流不变）。
- 关系创建改为**选端点**：从本域已有实体里选 from/to（不能手打 key），关系 kind 只列模板声明的 `relationship_kinds`。
- 新增**批量导入**：粘贴 JSON（`units` / `relationships` 两段）→ 干运行预览（逐行判词表、判端点、判重复）→ 确认后逐行走内核，返回逐行结果（created/updated/skipped/failed + 原因）。
- 台账增加「谁在什么时候改了什么」：复用 `authoring_events`，本域最近 N 条可展开。
- 权限：读沿用 `content:read`（annotator+）；写（建/改/删/导入）要求 `can_write`（expert+）；删除另要求 `lead`（软删可恢复，但删的是语义资产）。

## Capabilities

### New Capabilities

- `ontology-authoring`: 域本体的编辑与批量导入契约——实体/关系的写入必须经内核、kind 必须属于该域模板声明的词表、关系端点必须指向本域已存在的实体、批量导入必须先给出逐行预判再落库、每次写入都要留一条 append-only 事件。

### Modified Capabilities

- `domain-estate-console`: 「本体」区从只读台账改为可编辑台账（列表 + 建/改/删 + 导入入口），未整理状态必须显式可见（冒烟数据不得被当成内容）。

## Impact

- 代码：`src/web/routes/console.py`（ontology 区写路由）、`src/bench/authoring.py`（如缺则补「按域列出实体候选」的读函数）、`src/bench/store.py`（列表筛选查询）、`src/web/templates/domain_console_ontology.html`、`src/web/i18n.py`。
- 复用而非新造：`authoring_create_unit/update_unit/delete_unit/create_relationship/delete_relationship`、`authoring_events`、`relationship_external_key`、模板词表解析（`templates`/`inheritance`）。本变更**不新增** `knowledge_units` 写路径。
- 数据：无 schema 变更（`knowledge_units` 已够用）。生产里那 11 条冒烟单元需人工确认是否清理，本变更只提供删除能力。
- 风险：软删/恢复、批量导入的重复判定（`(kind, namespace, external_key)` 唯一键已在），以及「关系端点指向已软删实体」的处理——导入与关系创建都要拒。
