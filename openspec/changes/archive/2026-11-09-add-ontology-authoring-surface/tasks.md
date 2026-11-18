## 1. 读面：按域查单位（页面与导入共用）

- [x] 1.1 `authoring_list_units` 扩到能按 `kind` / 关键词 / 是否含已删过滤，并返回软删标记；验证＝单测：造 3 条（2 实体 1 关系、其中 1 条软删），三种过滤各自返回预期集合
- [x] 1.2 新增「本域未软删实体」读函数（供关系端点选择器与导入解析用），返回 `(external_key, body)` 且排除 `tags->>'deleted'='true'`；验证＝单测：软删的实体不出现在候选里
- [x] 1.3 实体详情读：给定 external_key，返回该单位的属性、层级、事件轨迹、以及**引用它的关系**；验证＝单测：建 from=A→to=B 后，A 与 B 的详情都能列出这条关系

## 2. 单条写入面（经内核）

- [x] 2.1 `POST /d/{domain}/ontology/units`：创建/更新实体（kind 取模板 `entity_types`、key/body/attrs、可选 tier），走 `authoring_create_unit`；验证＝单测：成功留 created 事件；词表外 kind 被拒且库内无变化
- [x] 2.2 `POST /d/{domain}/ontology/units/{key}/delete`：软删，要求 lead；验证＝单测：expert 403、lead 成功且 `tags.deleted` 落上、事件留痕
- [x] 2.3 `POST /d/{domain}/ontology/relations`：from/to 用 `external_key` 提交，服务端解析为未软删实体，走 `authoring_create_relationship`；验证＝单测：端点已软删被拒并说明；kind 不在 `relationship_kinds` 被拒
- [x] 2.4 删除实体时若被关系引用：不级联，返回被引用条数并在页面提示；验证＝单测：存在 2 条引用时删除成功且两条关系仍在（页面标出悬空）

## 3. 批量导入（同一校验器）

- [x] 3.1 `plan_import(conn, domain, payload)`：逐行产出 `create|update|skip|error` + 原因；校验项＝kind 词表、关系端点存在且未删、按 `(kind, namespace, external_key)` 判重；验证＝单测：20 实体 + 10 关系里混入 1 个坏 kind、1 个坏端点，计划里正好这两行 error
- [x] 3.2 `POST /d/{domain}/ontology/import?dry=1`：返回逐行预判，**不写库**；验证＝单测：调用前后 `knowledge_units` 行数不变（对应规格「干运行不写库」）
- [x] 3.3 `POST /d/{domain}/ontology/import`（确认）：消费同一计划逐行调内核，返回 `{created, updated, failed[]}`；验证＝单测：第二次导入同一份内容，created=0 且 updated=行数
- [x] 3.4 导入内容解析：`{"units": [...], "relationships": [...]}`，字段缺失/类型错的行报具体原因而不是整体 500；验证＝单测：给一个 `units` 是字符串的载荷，得到 400 + 可读错误

## 4. 页面与状态可见性

- [x] 4.1 本体区加「单位列表」：按 kind 分组、显示 tier 与软删标记、可按关键词筛；验证＝页面测试：造数据后列表出现对应 kind 与 key
- [x] 4.2 零实例的声明类型与「冒烟」测试数据分两处显示（前者算覆盖缺口，后者提示清理）；验证＝页面测试：模板声明 3 类型只填 1 个时，另 2 个出现在缺口区；含「冒烟」的 key 出现在测试数据区
- [x] 4.3 无写权限时不渲染任何写入表单（只读台账不变）；验证＝页面测试：annotator 的页面里没有 `method="POST"` 的单位表单
- [x] 4.4 最近事件可展开（谁/何时/动作/前后状态），默认折叠；验证＝页面测试：写入后事件区出现该条 key

## 5. 收口

- [x] 5.1 `openspec validate add-ontology-authoring-surface --strict` 通过
- [x] 5.2 全量 pytest 不回归（基线 1518 passed / 60 skipped）
- [x] 5.3 生产验证：用生产 legal 域跑一次「干运行 → 确认」的小批量（2 实体 1 关系），确认事件留痕与页面显示，随后按需清理该批次
- [x] 5.4 验收报告：写入经内核（事件行）、词表闸、端点校验、导入幂等、只读身份不见表单，各留一条可复核证据
