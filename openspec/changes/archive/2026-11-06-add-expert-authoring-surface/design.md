# 设计：专家创作与维护面

总纲：`docs/knowledge-platform-blueprint.md`（C2）。C1 已落模板+工作区+RBAC（`ontology-template`/`domain-workspace` 已上 spec）；本 change 落生产面。

## D1 域隔离载体 = KU namespace，零新身份存储

C1 已裁「平台不另存本体身份」的反面教训（C3 才翻权威源）；创作台产出的本体内容**就是内核 KU**：`upsert_knowledge_unit(conn, kind=..., namespace=domain.key, external_key=..., tier="raw", provenance={...})`。理由：

- KU 已有 `(kind, namespace, external_key)` 唯一性与四层 tier/溯源，天然满足「词表内落库、初始 raw、操作者入溯源」；
- 域隔离免费获得：namespace=域 key 即租户边界，`list_units`/读取按 namespace 过滤，跨域不可见不靠应用层自觉；
- C3 发布时直接按 namespace+域聚合导出，不用迁移。

边界：namespace 承载域隔离是**约定**（KU 表本身不强制 namespace∈domains.key）——执法在 `authoring.py` 写入口（先 `get_domain` 校验域存在，再取其 key 作 namespace），spec 场景由该入口保证；直插 DB 绕过入口不在契约内（沿 C1「写面纪律」同款处理）。

## D2 词表执法落点

执法函数在 `src/bench/authoring.py` 写入口（不在 KU 收口里加分支——`bench-platform` 域包插拔契约禁止内核长领域逻辑；词表本身是域数据，执法读的是域模板，属「平台消费域数据」而非「内核长领域分支」）：

```
authoring_create_unit(conn, *, domain_key, kind, external_key, body, operator_sub, tags, attrs)
  1. get_domain(domain_key) -> None 则 ValueError（域不存在）
  2. 取域锚定模板版本的 schema.entity_types -> kind 不在则 ValueError 报词表
  3. upsert_knowledge_unit(..., namespace=domain.key, tier="raw", provenance={"operator": sub, "via": "authoring"})
  4. 同事务落 authoring_events（op=create）
authoring_update_unit / authoring_delete_unit 同构（update 落 before/after；delete=KU 打 deleted 标记还是物理删？）
```

**删除语义**：物理删会撕裂事件流的可回放性；KU 无 soft-delete 列——本 change 选**事件流记 delete + KU 行保留打 `tags["deleted"]=true`**（upsert 更新 tags），浏览面过滤。理由：零内核改动、事件可回放、C3 发布面天然排除已删项。替代方案（加列/物理删）都动内核或撕裂历史，不取。

关系即 KU：`kind` 用模板 `relationship_kinds` 词表，`external_key` 约定 `<from_key>-><kind>:<to_key>` 确定性生成（保证幂等 upsert 与唯一性），`attrs` 存 `{from, to, from_key, to_key}` 结构化引用。关系词表执法与实体同路径。

## D3 两张新表（进 `WORKSPACE_SCHEMA`，同幂等注册）

```
authoring_events   id, domain_id FK, unit_kind TEXT, unit_key TEXT, op TEXT(create|update|delete),
                   before JSONB NULL, after JSONB NULL, operator TEXT NOT NULL,
                   via TEXT NOT NULL DEFAULT 'authoring', created_at
                   —— append-only：无 UPDATE/DELETE 路径；索引 (domain_id, unit_kind, unit_key), (domain_id, created_at)
authoring_tasks    id, domain_id FK, assignee TEXT NOT NULL, title TEXT NOT NULL, detail TEXT,
                   target_kind TEXT NULL, target_key TEXT NULL, status TEXT NOT NULL DEFAULT 'pending'
                   (pending|in_progress|done|cancelled), created_by TEXT NOT NULL,
                   created_at, updated_at
                   —— 状态流转留痕走 authoring_events？否：任务不是 KU，单独 task_events 太重；
                   用 updated_at + status 即可（spec 只要求「留痕谁何时置何态」→ 轻量做法：transitions JSONB
                   数组列 append {from,to,by,at}）——加一列 transitions JSONB NOT NULL DEFAULT '[]'
```

裁决：任务留痕用 `transitions` JSONB append 列，不另建表——量小、查询模式固定（详情页展示）、避免第三张表。

## D4 角色边界（与 C1 RBAC 合成）

- 工作台读（我的任务/浏览/事件查看）：域内任一角色（annotator 起）+ 平台 `content:read`；
- 写（create/update/delete/任务领取）：`expert` 起 + 平台 `content:write`；
- 任务指派/取消：`lead` 起 + 平台 `content:write`；
- 全部路由：`Depends(require_scope(...))` + `Depends(require_domain_role(...))` 两道序贯（C1 模式），admin 直通。

## D5 页面（域工作台，非 admin 门）

- `/domains/{domain_key}`（C1 已有 admin 门下域详情；**创作台是成员门**，放 `/workbench/{domain_key}`*）：
  - `GET /workbench/{domain_key}`：我的任务 + 域内容概览（按 kind 分组计数）
  - `GET /workbench/{domain_key}/browse/{kind}`：该 kind 内容列表（词表内 kind 才可达，出表 404）
  - `GET/POST /workbench/{domain_key}/units/{kind}/new`、`/units/{unit_key}`（编辑+事件历史）、`POST .../delete`
  - `POST /workbench/{domain_key}/tasks/{task_id}/status`（领取/完成）；lead 专属 `POST /tasks/new`
  - 导航：「我的域」（C1 已有）加每域工作台入口
- i18n 双语；`base.html` 不新增 admin 项。

## D6 非目标与风险

- 非目标见 proposal（C3 发布、diff/回滚 UI、AI 辅助）；
- 风险①：`external_key` 生成约定（关系键拼接）是 C3 发布与 wire 身份对齐的伏笔——本 change 把键约定写死在 `authoring.py` 常量与 docstring，C3 复用不重造；
- 风险②：任务表是最小闭环（无提醒/截止/工作量），够 P1 验证即可，规模化另立；
- 风险③：`upsert_knowledge_unit` 的 `ON CONFLICT DO UPDATE` 会让 update 与 create 在 KU 层同形——事件流的 op 判定以「写前是否存在」判定（先 SELECT 再写，同事务），不依赖 KU 返回值区分。
