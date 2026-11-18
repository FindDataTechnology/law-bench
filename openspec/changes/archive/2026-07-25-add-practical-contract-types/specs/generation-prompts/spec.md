## ADDED Requirements

### Requirement: Practical Contract Type Drafting Prompts
The system SHALL seed a matching set of 22 per-type drafting prompts for the practical (中国合同分类法 Part 2) contract types, one per practical rubric type key: `company_formation`, `equity_transfer`, `capital_increase`, `merger_acquisition`, `equity_incentive`, `vam_agreement`, `equity_holding_in_trust`, `real_estate_sale`, `real_estate_lease`, `employment`, `labor_dispatch`, `ip_license`, `franchise`, `real_estate_development`, `insurance`, `trust`, `private_equity_fund`, `software_development`, `film_production`, `talent_agency`, `ppp_project`, `tourism_service`. Each SHALL be named `draft_<type>`, with `contract_type` set to the type key (loose coupling, no foreign key), `purpose = drafting`, `source = local`, `prompt_type = baseline`, and a `content` body that is a Chinese drafting instruction tailored to that type's mandatory clauses (mirroring the per-type rubric theme). The seeding script (`scripts/seed_contract_prompts.py`) SHALL seed both the 民法典 prompts and these practical prompts in one idempotent pass and SHALL NOT modify any row in `rubrics` or `criteria`.

#### Scenario: Seed the 22 practical-type prompts
- **WHEN** `seed_contract_prompts.py` runs against a database that already has the 19 民法典 drafting prompts
- **THEN** 22 new `draft_<type>` prompt rows are inserted with `contract_type` = the type key, `purpose = drafting`, `source = local`, and `prompt_type = baseline`
- **AND** each prompt's `content` is a Chinese drafting instruction for that practical type's mandatory clauses
- **AND** the 19 民法典 prompts are unchanged

#### Scenario: Re-seeding practical-type prompts is idempotent
- **WHEN** `seed_contract_prompts.py` is run a second time
- **THEN** the `prompts` row count is unchanged
- **AND** no duplicate prompt rows are created
- **AND** the `rubrics` and `criteria` row counts are unchanged

#### Scenario: Practical prompts are tagged baseline and loosely coupled
- **WHEN** the 22 practical prompts are fetched
- **THEN** each has `prompt_type = baseline` and `contract_type` equal to its type key
- **AND** no foreign key binds the prompt's `contract_type` to a rubric, so deleting or renaming a rubric does not invalidate the prompt

#### Scenario: Practical prompt type keys match the practical rubric type keys
- **WHEN** the practical prompt `contract_type` values and the practical rubric `<type>` segments are compared
- **THEN** the two sets of type keys are identical
- **AND** each `draft_<type>` prompt corresponds to exactly one `contract_<type>_v1` rubric
