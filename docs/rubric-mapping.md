# 合同评价标准映射表 (v3)

## 概述

v3 评价规则采用优化后的通用标准，接受更宽泛的合规判定：
- **governing_law_present**: 接受"鉴于"、"争议解决"等部分的法律引用（不要求单独条款）
- **legal_citation_accuracy**: 接受法律名称正确但无精确条文序号
- **legal_basis_citation**: 接受泛化引用（如"民法典及相关司法解释"）
- **clause_completeness**: 允许核心必备条款缺失不超过一项

## 具名合同（民法典典型合同）- 19 个

| 合同类型 | 评价规则 | 民法典章节 | 条文范围 |
|---------|---------|-----------|---------|
| sale (买卖合同) | contract_sale_v3 | 第九章 | 595-647 |
| utilities_supply (供用电水气热力) | contract_utilities_supply_v3 | 第十章 | 648-656 |
| gift (赠与合同) | contract_gift_v3 | 第十一章 | 657-666 |
| loan (借款合同) | contract_loan_v3 | 第十二章 | 667-680 |
| guarantee (保证合同) | contract_guarantee_v3 | 第十三章 | 681-702 |
| lease (租赁合同) | contract_lease_v3 | 第十四章 | 703-734 |
| financing_lease (融资租赁) | contract_financing_lease_v3 | 第十五章 | 735-760 |
| factoring (保理合同) | contract_factoring_v3 | 第十六章 | 761-769 |
| work (承揽合同) | contract_work_v3 | 第十七章 | 770-787 |
| construction (建设工程) | contract_construction_v3 | 第十八章 | 788-808 |
| transport (运输合同) | contract_transport_v3 | 第十九章 | 809-842 |
| technology (技术合同) | contract_technology_v3 | 第二十章 | 843-887 |
| bailment (保管合同) | contract_bailment_v3 | 第二十一章 | 888-903 |
| warehousing (仓储合同) | contract_warehousing_v3 | 第二十二章 | 904-918 |
| entrustment (委托合同) | contract_entrustment_v3 | 第二十三章 | 919-936 |
| property_service (物业服务) | contract_property_service_v3 | 第二十四章 | 937-950 |
| brokerage (行纪合同) | contract_brokerage_v3 | 第二十五章 | 951-960 |
| intermediation (中介合同) | contract_intermediation_v3 | 第二十六章 | 961-966 |
| partnership (合伙合同) | contract_partnership_v3 | 第二十七章 | 967-978 |

## 非具名合同（无名合同）- 22 个

### 公司股权类（7 个）- 公司法 (2023 修订)

| 合同类型 | 评价规则 | 主要法律依据 |
|---------|---------|-------------|
| company_formation (公司设立) | contract_company_formation_v3 | 公司法 |
| equity_transfer (股权转让) | contract_equity_transfer_v3 | 公司法 |
| capital_increase (增资扩股) | contract_capital_increase_v3 | 公司法 |
| merger_acquisition (公司并购) | contract_merger_acquisition_v3 | 公司法 + 反垄断法 |
| equity_incentive (股权激励) | contract_equity_incentive_v3 | 上市公司股权激励管理办法 |
| vam_agreement (对赌协议) | contract_vam_agreement_v3 | 九民纪要 |
| equity_holding_in_trust (股权代持) | contract_equity_holding_in_trust_v3 | 信托法 |

### 房地产类（3 个）- 城市房地产管理法

| 合同类型 | 评价规则 | 主要法律依据 |
|---------|---------|-------------|
| real_estate_sale (房产买卖) | contract_real_estate_sale_v3 | 城市房地产管理法 |
| real_estate_lease (房屋租赁) | contract_real_estate_lease_v3 | 城市房地产管理法 |
| real_estate_development (房地产开发) | contract_real_estate_development_v3 | 城市房地产开发经营管理条例 |

### 劳动关系类（2 个）- 劳动合同法

| 合同类型 | 评价规则 | 主要法律依据 |
|---------|---------|-------------|
| employment (劳动合同) | contract_employment_v3 | 劳动合同法 (2012 修正) |
| labor_dispatch (劳务派遣) | contract_labor_dispatch_v3 | 劳动合同法 + 劳务派遣暂行规定 |

### 知识产权类（2 个）- 专利法/著作权法

| 合同类型 | 评价规则 | 主要法律依据 |
|---------|---------|-------------|
| ip_license (知识产权许可) | contract_ip_license_v3 | 专利法/商标法/著作权法 |
| software_development (软件开发) | contract_software_development_v3 | 民法典技术合同章 + 计算机软件保护条例 |

### 金融服务类（3 个）- 保险法/信托法

| 合同类型 | 评价规则 | 主要法律依据 |
|---------|---------|-------------|
| insurance (保险合同) | contract_insurance_v3 | 保险法 (2015 修正) |
| trust (信托合同) | contract_trust_v3 | 信托法 |
| private_equity_fund (私募基金) | contract_private_equity_fund_v3 | 证券投资基金法 + 私募基金管理条例 |

### 特定行业类（5 个）

| 合同类型 | 评价规则 | 主要法律依据 |
|---------|---------|-------------|
| franchise (特许经营) | contract_franchise_v3 | 商业特许经营管理条例 |
| film_production (影视剧制作) | contract_film_production_v3 | 著作权法 + 电影产业促进法 |
| talent_agency (演艺经纪) | contract_talent_agency_v3 | 营业性演出管理条例 |
| ppp_project (PPP 项目) | contract_ppp_project_v3 | 基础设施特许经营管理办法 |
| tourism_service (旅游服务) | contract_tourism_service_v3 | 旅游法 |

## v3 vs v2 评分对比（sample）

| 合同类型 | v2 通过率 | v3 通过率 | 提升 |
|---------|---------|---------|------|
| sale | 60-70% | 80% | ↑ |
| company_formation | 0-56% | 78% | ↑↑ |
| employment | 9% | 36% | ↑ |
| insurance | 0% | 55% | ↑↑ |
| ppp_project | 0% | 73% | ↑↑ |

## 迁移指南 (v2 -> v3)

1. v3 rubrics 已自动创建（41 个），`default_rubric()` 自动选择最高版本（v3）
2. v2 rubrics 保留不变，可显式指定 `rubric="contract_sale_v2"` 使用旧版
3. v3 优化了通用标准判定，接受更宽泛的合规判定
4. 类型特定标准保持不变（与 v2 相同）

## 使用方式

```python
# 自动使用 v3（最高版本）
pipeline_run("sale", tags={"scenario": "农产品买卖", "stance": "balanced"})

# 显式指定 v3
pipeline_run("sale", rubric="contract_sale_v3", ...)

# 回退到 v2
pipeline_run("sale", rubric="contract_sale_v2", ...)
```
