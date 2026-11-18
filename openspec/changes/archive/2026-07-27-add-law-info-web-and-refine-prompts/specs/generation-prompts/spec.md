## ADDED Requirements

### Requirement: Law-Refined Variant Drafting Prompts
The system SHALL seed a second set of per-contract-type drafting prompts - the **law-refined** variants - one per contract type key (the same 41 keys covered by the baseline: 19 民法典 types + 22 practical types). Each SHALL be named `draft_<type>_v2`, with `contract_type` set to the type key (loose coupling, no foreign key), `purpose = drafting`, `source = local`, and `prompt_type = law-refined`. Each prompt's `content` SHALL be a Chinese drafting instruction whose mandatory-clause list is grounded in that type's law_info survey - explicitly naming the governing statutes, judicial interpretations, and (where relevant) article ranges (e.g. for `sale`: 《民法典》合同编第八章买卖合同第595–647条、法释〔2020〕17号、法释〔2023〕13号). The seeding script (`scripts/seed_contract_prompts.py`) SHALL seed the baseline `draft_<type>` prompts AND these `draft_<type>_v2` prompts in one idempotent pass, SHALL NOT modify any baseline `draft_<type>` row (upsert matches by name; the names differ), and SHALL NOT modify any row in `rubrics` or `criteria`.

#### Scenario: Seed the 41 law-refined variant prompts
- **WHEN** `seed_contract_prompts.py` runs against a database that already has the 41 baseline `draft_<type>` prompts
- **THEN** 41 new `draft_<type>_v2` prompt rows are inserted with `contract_type` = the type key, `purpose = drafting`, `source = local`, and `prompt_type = law-refined`
- **AND** each prompt's `content` names the governing statutes/interpretations drawn from that type's law_info survey
- **AND** the 41 baseline `draft_<type>` prompts are unchanged

#### Scenario: Re-seeding law-refined prompts is idempotent
- **WHEN** `seed_contract_prompts.py` is run a second time
- **THEN** the `prompts` row count is unchanged
- **AND** no duplicate prompt rows are created
- **AND** the `rubrics` and `criteria` row counts are unchanged

#### Scenario: Baseline prompts are not modified by the v2 seed
- **WHEN** `seed_contract_prompts.py` runs after the v2 variants already exist
- **THEN** every baseline `draft_<type>` row retains its original `content` and `prompt_type = baseline`
- **AND** no baseline row is overwritten by the seeder

#### Scenario: Law-refined prompts are tagged and loosely coupled
- **WHEN** the 41 `draft_<type>_v2` prompts are fetched
- **THEN** each has `prompt_type = law-refined` and `contract_type` equal to its type key
- **AND** no foreign key binds the prompt's `contract_type` to a rubric, so deleting or renaming a rubric does not invalidate the prompt

#### Scenario: Law-refined prompts are usable in compare runs
- **WHEN** a compare run is created using a `draft_<type>_v2` prompt
- **THEN** the run's `prompt_name` and `prompt_type` snapshot columns record `draft_<type>_v2` and `law-refined` respectively
- **AND** the baseline `draft_<type>` prompt can be compared against the v2 variant in the same compare run
