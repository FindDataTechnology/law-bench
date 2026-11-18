## ADDED Requirements

### Requirement: Per-Class Chinese Contract Rubrics
The system SHALL support an idempotently-seeded set of per-class Chinese contract rubrics - one per 民法典 typical named contract type (买卖合同, 供用电水气热力, 赠与合同, 借款合同, 保证合同, 租赁合同, 融资租赁, 保理合同, 承揽合同, 建设工程, 运输合同, 技术合同, 保管合同, 仓储合同, 委托合同, 物业服务, 行纪合同, 中介合同, 合伙合同). Each SHALL be stored with `source = local` and `context = contract`, named `contract_<type>_v1`, and SHALL consist of the shared base criteria (party identification, governing law, clause completeness, legal citation accuracy) plus 4-6 type-specific Chinese criteria drawn from that type's 民法典 mandatory-clause set. The seeding script (`scripts/seed_contract_rubrics.py`) SHALL be idempotent and SHALL NOT modify or delete any row whose `source` is not `local`.

#### Scenario: Seed the 19 per-class rubrics
- **WHEN** `seed_contract_rubrics.py` runs against a database with only the harbor rubrics and `contract_drafting_v1`
- **THEN** 19 new `contract_<type>_v1` rubrics are inserted with `source = local` and `context = contract`
- **AND** each rubric has the 4 shared base criteria plus its 4-6 type-specific criteria

#### Scenario: Re-seeding per-class rubrics is idempotent
- **WHEN** `seed_contract_rubrics.py` is run a second time
- **THEN** the rubric and criteria row counts are unchanged
- **AND** no duplicate rubric or criterion rows are created

#### Scenario: Per-class rubrics coexist with harbor rubrics
- **WHEN** the 19 per-class local rubrics exist alongside the harbor rubrics
- **THEN** both are stored in the same `rubrics`/`criteria` tables without conflict
- **AND** subsequent harbor re-extraction leaves the per-class local rubrics unchanged
