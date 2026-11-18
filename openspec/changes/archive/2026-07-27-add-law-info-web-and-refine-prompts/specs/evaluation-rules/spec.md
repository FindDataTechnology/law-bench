## ADDED Requirements

### Requirement: Law-Refined Variant Contract Rubrics
The system SHALL seed a second set of per-class Chinese contract rubrics - the **law-refined** variants - one per contract type key (the same 41 keys covered by the v1 rubrics: 19 民法典 types + 22 practical types). Each SHALL be named `contract_<type>_v2`, stored with `source = local` and `context = contract`, and SHALL consist of the 4 shared base criteria (party identification, governing law, clause completeness, legal citation accuracy) plus 4-6 type-specific Chinese criteria whose `guidance` references the correct governing statutes and judicial interpretations for that type as surfaced by the law_info survey (e.g. for `sale`: citing 《最高人民法院关于审理买卖合同纠纷案件适用法律问题的解释》法释〔2020〕17号 and the 民法典 595–647条 range; for `employment`: citing 《劳动合同法》; for `insurance`: citing 《保险法》). The seeding script (`scripts/seed_contract_rubrics.py`) SHALL seed the v1 rubrics AND these `contract_<type>_v2` rubrics in one idempotent pass, SHALL NOT modify any v1 `contract_<type>_v1` row (upsert matches by name; the names differ), and SHALL NOT modify or delete any row whose `source` is not `local`.

#### Scenario: Seed the 41 law-refined variant rubrics
- **WHEN** `seed_contract_rubrics.py` runs against a database that already has the 41 v1 `contract_<type>_v1` rubrics
- **THEN** 41 new `contract_<type>_v2` rubrics are inserted with `source = local` and `context = contract`
- **AND** each v2 rubric has the 4 shared base criteria plus its 4-6 type-specific criteria whose guidance cites the correct governing statutes from the law_info survey
- **AND** the 41 v1 rubrics are unchanged

#### Scenario: Re-seeding law-refined rubrics is idempotent
- **WHEN** `seed_contract_rubrics.py` is run a second time
- **THEN** the rubric and criteria row counts are unchanged
- **AND** no duplicate rubric or criterion rows are created

#### Scenario: v1 rubrics are not modified by the v2 seed
- **WHEN** `seed_contract_rubrics.py` runs after the v2 rubrics already exist
- **THEN** every v1 `contract_<type>_v1` rubric and its criteria retain their original content
- **AND** no v1 row is overwritten by the seeder

#### Scenario: v2 rubrics coexist with v1 and harbor rubrics
- **WHEN** the 41 v2 rubrics exist alongside the 41 v1 rubrics, the sample rubric, and the harbor rubrics
- **THEN** all are stored in the same `rubrics`/`criteria` tables without conflict
- **AND** subsequent harbor re-extraction leaves every local rubric (v1 + v2 + sample) unchanged

#### Scenario: v2 rubric criteria cite accurate statutes
- **WHEN** the `contract_sale_v2` rubric's type-specific criteria are inspected
- **THEN** at least one criterion's guidance references the 买卖合同 judicial interpretation (法释〔2020〕17号) or the 民法典 595–647条 range
- **AND** no criterion cites a fabricated or repealed statute as currently in force
