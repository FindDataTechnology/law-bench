## Why

The evaluation and generation system currently covers only the 19 《民法典》典型有名合同 (Part 1 of `chinese_contracts_class.md`) - 19 per-class rubrics, 19 drafting prompts, and 19 zh/en labels. The file's Part 2 - the "中国合同分类法" 实务体系 (法天使, 5000+ templates, up to six levels) - is not represented at all. Practical contract types that dominate real legal work (股权转让, 增资, 并购, 对赌, 股权激励, 劳动合同, 特许经营, 房地产开发, 保险, 信托, 私募基金, 软件开发, 影视, 演艺, PPP, 旅游…) cannot be drafted against a type-specific rubric or compared with a type-specific prompt. The catalog should be extended so the eval + generation pipeline serves practical, industry-specific contracts, not just the statutory 民法典 set.

## What Changes

- Extend `scripts/seed_contract_rubrics.py` with 22 new `contract_<type>_v1` rubrics for non-overlapping Part 2 practical types - one per type, each = the 4 shared base criteria + 4-6 type-specific Chinese criteria drawn from that type's governing statute (公司法, 劳动法/劳动合同法, 保险法, 信托法, 城市房地产管理法, 商业特许经营管理条例, 旅游法, …), not just 民法典.
- Extend `scripts/seed_contract_prompts.py` with 22 matching `draft_<type>` prompts (`purpose = drafting`, `prompt_type = baseline`, `contract_type = type_key`), each a Chinese drafting instruction tailored to that type's mandatory clauses.
- Extend `src/web/i18n.py` `LABELS["contract_type"]` with the same 22 keys in both `zh` and `en`, preserving the zh/en parity contract.
- Update `tests/test_i18n.py`: the exact-set assertion `test_label_catalog_has_19_contract_types` becomes a union assertion over the 19 民法典 types **plus** the 22 practical types.
- Skip the ~10 Part 2 sub-types that 1:1 duplicate the 民法典 19 (民间借贷/借款, 担保/保证, 委托/委托, 中介居间/中介, 行纪寄售/行纪, 保管仓储/保管+仓储, 建设工程细分/建设工程, 物流运输/运输, 公用事业/供用, 融资租赁, 合伙协议/合伙) - no redundant rubrics or prompts.
- **Out of scope**: the file is incomplete (Part 2 cut off mid-C at 旅游; D门类 and K类 have no details). Only the A/B/C sub-types present in the file are seeded; D/K are not inferred.

## Capabilities

### New Capabilities
<!-- none - no new spec area; the per-type rubric/prompt capabilities already exist and are extended. -->

### Modified Capabilities
- `evaluation-rules`: the "Per-Class Chinese Contract Rubrics" requirement is extended from "one per 民法典 typical named contract type (19)" to also cover a second idempotently-seeded set of practical (中国合同分类法 Part 2) contract types. The new rubrics reuse the same `source = local` / `context = contract` / `contract_<type>_v1` convention and the same 4 shared base criteria; their type-specific criteria are drawn from each type's governing statute beyond 民法典.
- `generation-prompts`: the "Idempotent Prompt Seeding" and "Prompt Type (Variant Lineage)" requirements are extended so the seeded registry covers the same 22 practical types in addition to the 19 民法典 types, each with `prompt_type = baseline` and `contract_type` set to the practical type key (loose coupling, no FK).

## Impact

- **Modified files**: `scripts/seed_contract_rubrics.py` (append 22 `_rubric()` entries to `RUBRICS`), `scripts/seed_contract_prompts.py` (append 22 `_p()` entries to `PROMPTS`), `src/web/i18n.py` (22 keys added to `LABELS["zh"]["contract_type"]` and `LABELS["en"]["contract_type"]`), `tests/test_i18n.py` (exact-set test -> union test, renamed).
- **Unchanged**: `BASE_CRITERIA`/`_c`/`_rubric`/`main()` in the rubric seeder, `upsert_local_prompt`/`_p`/`main()` in the prompt seeder, the DB schema (`scripts/extract_harbor_rules.py` `SCHEMA`), `title_for_prompt`/`title_for_rubric` (derivation regexes already match `draft_<key>` / `contract_<key>_v1`), the generation crew (`src/crew.py`, `config/*.yaml` - contract type is inferred by the intake agent, not hardcoded), and `templates/*.md` (shared reference templates, not per-type).
- **Data**: `db/evaluation_rules.db` grows from 20 local rubrics / 19 prompts to 42 local rubrics / 41 prompts after re-seeding (19 民法典 + 22 practical + 1 sample rubric; 19 + 22 prompts). Re-seeding is idempotent (upsert by name).
- **Dependencies**: none added.
- **Tests**: `tests/test_data_labels.py` and the rest of the suite are additive (they use fixture-created `sale`/`draft_sale` data, not the seeders) - no changes beyond `test_i18n.py`.
