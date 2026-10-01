# Tag Vocabulary Reference

Valid tag values and contract types for the Law Bench Contract Generation API.

This document is the offline reference for the `tags` field used across the API
(`POST /contracts/content`, `POST /contracts/batch`, `GET /tags/combinations/{type}`,
`POST /tags/validate`). For endpoint behavior, see
[API Reference](api-reference.md). For server setup, see
[API Server Setup](api-server.md).

---

## Table of Contents

- [Universal Tag Dimensions](#universal-tag-dimensions)
- [Type-Specific Dimensions](#type-specific-dimensions)
- [Scenario Vocabularies](#scenario-vocabularies)
- [Contract Type Catalog](#contract-type-catalog)

---

## Universal Tag Dimensions

These dimensions apply to **every** contract type. They are the baseline tag
vocabulary; type-specific dimensions (below) are added on top.

| Dimension | Key | Allowed values | Chinese label |
|-----------|-----|----------------|---------------|
| 来源 (source) | `source` | `base`, `tagged`, `custom` | 来源 |
| 利益倾向 (stance) | `stance` | `pro_a`, `pro_b`, `balanced` | 利益倾向 |
| 风险合规 (risk) | `risk` | `high`, `medium`, `low` | 风险合规 |
| 强度 (strength) | `strength` | `strong`, `standard`, `mild` | 强度 |
| 强制性 (mandatory) | `mandatory` | `mandatory`, `default`, `recommended` | 强制性 |

### Value semantics

- **`stance`** — which party the clause favors. `pro_a` favors 甲方 (party A),
  `pro_b` favors 乙方 (party B), `balanced` is neutral.
- **`source`** — clause provenance. `base` = 母版 template fallback,
  `tagged` = scenario-specific extracted clause, `custom` = curated override.
  Assembly precedence is `custom > tagged > base`.
- **`risk`** — compliance/risk level of the clause.
- **`strength`** — how strongly the obligation is worded.
- **`mandatory`** — whether the clause is legally mandatory, a default, or a
  recommendation.

> **Note:** `source` is metadata about clause provenance, not a generation
> input. When calling the API, you typically pass `stance` and `scenario`; the
> assembler resolves `source` internally.

---

## Type-Specific Dimensions

Each contract type can carry additional controlled dimensions beyond the
universal set. Below are the high-variation types as examples. For any type
not listed here, query `GET /tags/combinations/{type}` to discover its
dimensions live.

### sale (买卖合同)

| Dimension | Allowed values |
|-----------|----------------|
| `risk_transfer_node` | `on_delivery`, `at_port_of_shipment`, `at_destination`, `delivered_to_carrier` |
| `quality_objection_type` | `appearance_defect`, `hidden_defect`, `performance_failure` |
| `retention_of_title_status` | `unregistered`, `registered`, `not_applicable` |

### lease (租赁合同)

| Dimension | Allowed values |
|-----------|----------------|
| `priority_right_status` | `none`, `reserved`, `waived`, `requires_written_notice` |
| `subletting_authorization_mode` | `prohibited`, `requires_landlord_consent`, `record_only`, `free_sublet` |
| `accession_disposal_rule` | `restore_original`, `discounted_compensation`, `free_to_landlord` |

### employment (劳动合同)

| Dimension | Allowed values |
|-----------|----------------|
| `special_restriction_period` | `probation`, `service_period`, `non_compete`, `declassification`, `none` |
| `working_hours_system` | `standard`, `comprehensive`, `flexible`, `part_time` |

> Other types (e.g. `loan`, `guarantee`, `insurance`) may have their own
> dimensions registered at runtime. Use `GET /tags/combinations/{type}` or
> `GET /contracts/types/{type}` to enumerate them.

---

## Scenario Vocabularies

`scenario` (业务场景) captures the transaction sub-type. It is the primary
driver of tagged-clause selection. Every vocabulary ends with `其他` (other)
as the fallback for sub-types outside the seeded set.

> **Leniency:** `scenario` accepts any non-empty string — it is
> LLM-suggested and governance-extended, so the seeded vocab below is advisory
> (a UI dropdown) rather than a hard whitelist. Unknown scenario values are
> kept, not rejected.

| Contract type | Scenarios |
|---------------|-----------|
| `sale` | 农产品买卖, 消费品零售, 工业品建材, 展销会, 共享服务, 其他 |
| `service` | 教育培训, 驾校培训, 养老服务, 消费会员, 招投标服务, 其他 |
| `real_estate_lease` | 住宅租赁, 商业场地租赁, 其他 |
| `real_estate_sale` | 二手房买卖, 商品房买卖, 其他 |
| `entrustment` | 农业委托, 工程咨询, 设备管理委托, 其他 |
| `property_service` | 住宅物业, 电梯维保, 其他 |
| `construction` | 建设工程, 家庭装饰装修, 工程检测, 其他 |
| `lease` | 土地经营权流转, 水面承包, 物资租赁, 其他 |
| `work` | 测绘, 装饰装修, 种子繁育, 广告发布, 其他 |
| `intermediation` | 房地产经纪, 家政中介, 租赁中介, 电商服务, 其他 |
| `utilities_supply` | 燃气供应, 供热供应, 电力供应, 其他 |
| `tourism_service` | 团队境内游, 研学旅游, 出境旅游, 组团委托, 其他 |
| `transport` | 船舶租赁, 快递, 旅游用车, 港口作业, 多式联运, 其他 |
| `land_transfer` | 土地出让, 其他 |
| `insurance` | 人寿保险, 财产保险, 其他 |
| `loan` | 经营贷款, 消费贷款, 其他 |
| `employment` | 全日制用工, 非全日制用工, 其他 |
| `technology` | 技术开发, 技术转让, 其他 |
| `ip_license` | 许可使用, 其他 |
| `bailment` | 保管服务, 其他 |
| `warehousing` | 仓储服务, 其他 |
| `guarantee` | 保证担保, 其他 |
| `factoring` | 保理, 其他 |
| `franchise` | 特许经营, 其他 |

Types not listed above have no seeded scenario vocabulary; the extraction/retag
LLM registers values on the fly, so any non-empty scenario string is accepted.

---

## Contract Type Catalog

All 43 supported `contract_type` keys. Pass one of these as the `contract_type`
field in any request. To query live clause counts and metadata for a type, see
[`GET /contracts/types`](api-reference.md#get-contractstypes) and
[`GET /contracts/types/{contract_type}`](api-reference.md#get-contractstypescontract_type)
in the API reference.

| Key | Chinese name | Key | Chinese name |
|-----|--------------|-----|--------------|
| `bailment` | 保管合同 | `loan` | 借款合同 |
| `brokerage` | 行纪合同 | `merger_acquisition` | 公司并购协议 |
| `capital_increase` | 增资扩股协议 | `partnership` | 合伙合同 |
| `company_formation` | 公司设立合同 | `ppp_project` | PPP项目合同 |
| `construction` | 建设工程合同 | `private_equity_fund` | 私募基金合同 |
| `employment` | 劳动合同 | `property_service` | 物业服务合同 |
| `entrustment` | 委托合同 | `real_estate_development` | 房地产开发合同 |
| `equity_holding_in_trust` | 股权代持协议 | `real_estate_lease` | 房屋租赁合同 |
| `equity_incentive` | 股权激励协议 | `real_estate_sale` | 房产买卖合同 |
| `equity_transfer` | 股权转让合同 | `sale` | 买卖合同 |
| `factoring` | 保理合同 | `service` | 服务合同 |
| `film_production` | 影视剧合作制作合同 | `software_development` | 软件开发合同 |
| `financing_lease` | 融资租赁合同 | `talent_agency` | 演艺经纪合同 |
| `franchise` | 特许经营（加盟）合同 | `technology` | 技术合同 |
| `gift` | 赠与合同 | `tourism_service` | 旅游服务合同 |
| `guarantee` | 保证合同 | `transport` | 运输合同 |
| `insurance` | 保险合同 | `trust` | 信托合同 |
| `intermediation` | 中介合同 | `utilities_supply` | 供用电水气热力合同 |
| `ip_license` | 知识产权许可合同 | `vam_agreement` | 估值调整（对赌）协议 |
| `labor_dispatch` | 劳务派遣合同 | `warehousing` | 仓储合同 |
| `land_transfer` | 土地转让 | `work` | 承揽合同 |
| `lease` | 租赁合同 | | |

> **Note:** `land_transfer` and `service` have templates registered but may not
> appear in the law-info survey sources. They remain valid `contract_type`
> values for generation.
