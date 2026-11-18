# 本体模板分层

> 变更：`openspec/changes/add-layered-ontology-templates`。平台总纲见
> `docs/knowledge-platform-blueprint.md` §三；本文只讲**层**这一件事怎么用。

## 一句话

模板按层组织，每层有自己的权威与生命周期；**层内可继承，跨层只能对齐**。

## 四个层

| 层 | 权威 | 例子 | 谁维护 |
|---|---|---|---|
| `foundation` | `platform` | `organization` / `person` / `place` / `item` / `document` / `event` / `agreement` / `measurement` | 知验台 |
| `observation` | `external` | 30 个观测实体类型、14 个关系、30 个概念族 | `fd-open-data-protocol`（只读导入） |
| `industry` | `platform` | `enterprise-base`（客户/供应商/商品/科目/分录…）、`finance-market` | 行业专家 |
| `domain` | `platform` | `legal-domain`、`gov-domain` | 领域负责人 |

一个模板**不声明 `layer`** 也是合法的，它落在 `unlayered`——那是「分层概念出现之前」
的占位，不是第五个层。存量模板就是这么被保住的：不需要一次性迁移，且它永远无法继承
进任何一个已声明的层（这正是分层要拦的事）。

## 三条硬规则

**1. 层内可继承（`extends`），跨层不可。**

```jsonc
// 合法：两个 industry 层
{"layer": "industry", "extends": {"name": "erp-base", "version": 1}}
```

```jsonc
// 拒绝：foundation → industry
{"layer": "industry", "extends": {"name": "foundation-v1", "version": 1}}
// InheritanceError: extends crosses ontology layers: parent is 'foundation',
//                   child is 'industry'. ... declare cross-layer equivalence
//                   with 'aligned_with' instead.
```

为什么：继承意味着「同一份权威的两个版本」。跨层继承会让上游发一版就自动改变所有
下游模板的可用词表，而下游专家没有同意过那个变更。

**2. 跨层只声明对齐（`aligned_with`），不合并词表。**

```jsonc
"aligned_with": [
  {"target_template": "foundation-v1", "target_layer": "foundation",
   "type_map": {"company": "organization", "city": "place"}}
]
```

观测层的 `company` 是被观测对象（有 ticker、有 identifiers 表），foundation 的
`organization` 是交易主体（有 customer 关系、有合同）。**同一个所指，不同生命周期。**
合并在两者之间必须选一个权威，而两边都能举出反例。

读面用 `inheritance.aligned_types(conn, name=...)` 查这份声明；查不到就返回空，
不猜。

**3. 角色不是类型。**

`customer` / `vendor` / `employee` 是 `organization` 的**关系**，不是实体类型。
同一条需求也拒绝「同一个词既是类型又是关系」：

```jsonc
// 拒绝
{"entity_types": ["organization", "customer"], "relationship_kinds": ["customer"]}
```

理由在跨系统对齐：Salesforce 的 Account、金蝶的客户档案、知验台的客户，必须收敛成
**同一个** `organization` 实体、各挂一条角色关系。若各自是类型，对齐就发生在类型之间，
而类型之间没有稳定落点——那会需要一张「customer ↔ Acme GmbH」的映射表。

## 权威：平台 vs 外部

```jsonc
"authority": {"kind": "platform"}                                   // 这里可编辑
"authority": {"kind": "external", "source": "fd-open-data-protocol",
              "version": "2026.11"}                                  // 只读
```

`external` 模板的词表**不可就地修改**，只能重新导入产生新版本：

```
uv run python scripts/import_protocol_ontology.py --dry-run
uv run python scripts/import_protocol_ontology.py
```

原因：`fd-open-data-protocol` 是可安装的 PyPI 包，其 golden digest 测试钉死了
已发布内容。就地改会让两侧静默分叉，而分叉后没人知道哪一侧是权威。

## 尺子：模板必须可被评测

模板用 `rubric_refs` 声明「我用哪些尺子」。这条声明以前是一句注释，现在有闸：

- **保存时不阻断**（可以分步构造：先词表、后尺子），未解析项在模板详情页可见；
- **实例化时拒绝**任何声明了却解析不到的尺子；
- **升版要过 `no-worse` 门**：新版本不得比最近一条结论更差，`inconclusive`
  （判不出来）与 `fail` 一样不放行；
- **删掉尺子本身是退步**：否则「先删 `rubric_refs` 再升版」就是绕过门的现成路径。

升版走 `template_readiness.promote_template_via_gate()`；直接调 `update_template`
的只有一次性数据脚本（`tests/test_bench_template_gate_bypass.py` 逐个登记理由）。

## 已知边界

`concept_structures` 是**浅合并**：子模板要增补父模板已有类型的字段，只能整条重写该
类型，不能字段级追加。v1 不做字段级继承，读面在遇到这种需求时如实说明，不静默丢弃。

## 脚本

| 脚本 | 作用 |
|---|---|
| `scripts/register_layered_templates.py` | 落 `foundation-v1` / `enterprise-base` / `finance-market` |
| `scripts/import_protocol_ontology.py` | 只读导入 protocol 词表为 `external-world`（按 `(source, version)` 幂等） |
| `scripts/migrate_template_layers.py` | 为分层前的存量模板补 `layer` + `authority`（新增键，六键逐字节不变） |

全部支持 `--dry-run`，全部幂等。
