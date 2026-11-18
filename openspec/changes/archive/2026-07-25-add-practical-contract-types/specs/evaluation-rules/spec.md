## ADDED Requirements

### Requirement: Practical Contract Type Rubrics
The system SHALL support a second idempotently-seeded set of per-class Chinese contract rubrics covering practical (中国合同分类法 Part 2) contract types that are not already covered by the 民法典 typical named contract types. The seeded set SHALL comprise these 22 non-overlapping practical types: `company_formation`, `equity_transfer`, `capital_increase`, `merger_acquisition`, `equity_incentive`, `vam_agreement`, `equity_holding_in_trust` (门类 A - 公司股权); `real_estate_sale`, `real_estate_lease`, `employment`, `labor_dispatch`, `ip_license`, `franchise` (门类 B - 常见法律关系); `real_estate_development`, `insurance`, `trust`, `private_equity_fund`, `software_development`, `film_production`, `talent_agency`, `ppp_project`, `tourism_service` (门类 C - 特定行业). Each SHALL be stored with `source = local` and `context = contract`, named `contract_<type>_v1`, and SHALL consist of the same 4 shared base criteria (party identification, governing law, clause completeness, legal citation accuracy) plus 4-6 type-specific Chinese criteria drawn from that type's governing statute beyond 民法典 (e.g. 公司法, 劳动法/劳动合同法, 保险法, 信托法, 城市房地产管理法, 商业特许经营管理条例, 旅游法). The seeding script (`scripts/seed_contract_rubrics.py`) SHALL seed both the 民法典 set and this practical set in one idempotent pass, SHALL NOT modify or delete any row whose `source` is not `local`, and SHALL NOT seed a practical type that 1:1 duplicates a 民法典 type.

#### Scenario: Seed the 22 practical-type rubrics
- **WHEN** `seed_contract_rubrics.py` runs against a database that already has the harbor rubrics, the 19 民法典 per-class rubrics, and `contract_drafting_v1`
- **THEN** 22 new `contract_<type>_v1` rubrics are inserted with `source = local` and `context = contract`
- **AND** each practical rubric has the 4 shared base criteria plus its 4-6 type-specific criteria
- **AND** the 19 民法典 rubrics, the sample rubric, and the harbor rubrics are unchanged

#### Scenario: Re-seeding practical-type rubrics is idempotent
- **WHEN** `seed_contract_rubrics.py` is run a second time
- **THEN** the rubric and criteria row counts are unchanged
- **AND** no duplicate rubric or criterion rows are created

#### Scenario: Practical rubrics do not duplicate 民法典 types
- **WHEN** the seeded practical types are enumerated
- **THEN** none of them is a 1:1 duplicate of a 民法典 typical named contract type (no second rubric for 买卖/租赁/借款/担保/委托/建设工程/运输/保管/仓储/融资租赁/合伙)
- **AND** the borderline types `real_estate_sale`, `real_estate_lease`, and `software_development` are seeded as distinct types because their governing statute and mandatory clauses differ from the generic 民法典 rubric

#### Scenario: Practical rubrics coexist with all other rows
- **WHEN** the 22 practical local rubrics exist alongside the 民法典 rubrics, the sample rubric, and the harbor rubrics
- **THEN** all are stored in the same `rubrics`/`criteria` tables without conflict
- **AND** subsequent harbor re-extraction leaves every local rubric (民法典 + practical + sample) unchanged
