# 本体编辑与批量导入 · 验收（2026-11-09，镜像 `sha-5e949d9`）

## 一、为什么做

法律域有 364,916 块语料、11 条知识单元；这 11 条里 5 个「实体」是冒烟测试留下的
（`冒烟日期`/`冒烟订单`/`冒烟客户`/`冒烟桥表`/`冒烟订单×冒烟客户 连接`），真正
整理进本体的内容为零。内核 `authoring_*`（词表闸 + append-only 事件）与提案层都
在，**缺的是入口**：本体区原是纯只读台账。

## 二、五条规格逐条对证

| 规格 | 证据 |
|---|---|
| 本体单位可编辑但必须经内核 | 所有写入走 `authoring_*`；每个写入留事件（下方实测的 create 行） |
| 关系的两端必须是本域真实实体 | 端点由服务端对 `authoring_live_entities` 复核；软删/不存在的端点被拒 |
| 批量导入先预判再落库 | 干运行与落库共用 `ontology_import.plan()`；实测 dry 行数不变、confirm 才写 |
| 未整理状态显式可见 | 零实例的声明类型进「声明了但还没有内容」区；含 smoke/冒烟 的键进「疑似测试数据」区 |
| 本体区可编辑（域控制台） | 列表 + 建/改/软删/连关系/导入；无写权限时不渲染任何表单 |

## 三、生产实测（legal 域，探针批次已清理）

```
vocabularies: entity_types ['clause','law']
              relationship_kinds ['cites_law','superseded_by','belongs_to_contract_type']

第一次探针用了 cites（不在词表）→ 只写进 2 个实体，关系行被词表闸拒绝
                                    （这正是规格要的行为，也说明闸真的在拦）

第二次用真实词表：
dry wrote nothing: True
confirm wrote: 3
events: [('create','cites_law','probe-a->cites_law:probe-b'),
         ('create','law','probe-b'),
         ('create','clause','probe-a')]
relation visible from probe-a: [('cites_law','probe-b',False)]
cleanup ok: True        ← 探针行与事件已删除，legal 回到基线
```

## 四、测试

新增 27 条：`test_ontology_reads.py`(7) / `test_ontology_writes.py`(7) /
`test_ontology_import.py`(7) / `test_ontology_page.py`(6)。
全量 **1545 passed / 60 skipped**（基线 1518，零回归）。

其中两条专门钉住易错点：

- `test_limit_means_newest_n_matching_not_newest_n_then_filter` —— 过滤必须下推
  SQL，否则「最新 200 条恰好都被软删」会显示成一个空域；
- `test_deleting_an_entity_does_not_cascade_its_relations` —— 删除不级联，关系
  标 dangling（级联会静默扩大影响面）。

## 五、遗留

- 生产那 11 条冒烟单元仍在（页面已标「疑似测试数据」）。清不清由人决定，本轮
  只提供识别与逐条删除能力。
- 图谱可视化、从语料自动抽取候选实体/关系，都在 Non-Goals 里，属另一个变更。
