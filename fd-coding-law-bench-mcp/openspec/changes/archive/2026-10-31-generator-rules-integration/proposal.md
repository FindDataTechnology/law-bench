## Why

The `contract-generator` repo (cloned under `合同生成规则/`) implements a rules-as-data engine with 5 rule layers over a 73-leaf contract type tree: `intent.yaml` (type tree + 线索驱动走门 + param_doors), `elements/` (要素卡: id/name/required/type/prompt/大白话问法), `clauses/` ({{slot}} clause text + topic dedup + source=民法典§), `validation/` (硬约束: required/max/min/max_duration/regex/oneof/always, severity error/warning), `templates/` (stance_variants party_a/party_b). law-bench already shares the compatible primitives ({{slot}}, clause text, law_refs, stance, tag-driven assembly) but is missing four things the generator has: (a) a principled "required elements ⇒ mandatory 母版 clauses" completeness baseline, (b) the elements问法库 (大白话 prompt) and typed slots (enum/money/date/duration), (c) legal hard constraints (validation layer), and (d) ~23 contract families law-bench has no type for at all.

Three decisions were confirmed with the user:

1. For overlapping types, rewrite/supplement using the generator's required-marked elements as the 母版 baseline; design a scheme for the non-required/optional clause types.
2. Bring in the validation compliance constraints as a NEW standalone concept — explicitly NOT wired into the existing contract-generation/assembly flow.
3. Merge the generator's elements `prompt` (大白话问法) + `type` (enum/money/date/duration) into law-bench's existing `slot_instructions`.

## What Changes

- **MODIFIED** 母版 (base) clause sets for ~24 overlapping types (Category A): supplemented so every base set covers the generator's `required: true` elements; generator's 民法典-grounded review-driven clauses (优先承租权, 维修责任划分标准, 买卖不破租赁, 自然损耗界定…) merged in. Merge-not-replace: the generator's sparse clause text never overwrites law-bench's richer existing base (per `sale-quanyi-override-drops-rich-base` memory).
- **NEW** ~23 contract types (Category B — see design.md table) created in `contract_types` with base clauses seeded from the generator's `clauses/<type>.yaml`.
- **NEW** Sub-type / param-door leaves (e.g. `lease.immovable.{house,shop,office,warehouse,parking}`, `lease.equipment.{computer,printer,phone}`, `sale.{movable,real-estate,vehicle}`) become `tagged` clauses with `scenario` tags — the existing scenario-filtered assembly already consumes these.
- **NEW** `type_validations` table: standalone legal hard constraints (required/max/min/max_duration/max_deposit_months/regex/oneof/always) loaded from the generator's `validation/*.yaml`, each with `severity` (error/warning) and `law_ref` (民法典§). Exposed via new MCP tools. NOT called by assembly/fill/self-heal — a separate post-draft compliance check.
- **MODIFIED** `slot_instructions` (jsonb): each slot gains optional `prompt` (大白话问法) and `type` (text/money/date/duration/enum; enum carries `enum_values`). Generator's `required: true` elements map to `required: true` slots. Field-level inheritance (loan redefines root 甲方(出租方)→甲方(出借人)) handled via per-type slot override.

## Scope Decisions (confirmed)

1. **Rewrite = supplement, not replace.** The generator's clause text is sparse (e.g. `sale.yaml` = 7 bare clauses) vs law-bench's richer base (sale = 13 base incl. 检验期间/所有权保留). The generator's value is the required-element completeness checklist + 民法典-grounded supplements, not its bare strings. Required elements define WHICH clauses the 母版 must contain; content is merged.
2. **Validation is standalone.** `type_validations` is a read-only compliance layer run against a finished draft. The assembly pipeline (`contract_generate`, fill, `self_heal_pipeline_run`, `auto_reject_pipeline_run`) does NOT invoke it. Generation stays unchanged; validation evolves independently.
3. **Slot enrichment is additive.** `prompt`/`type` are optional jsonb keys on existing `slot_instructions`; no DDL, no breaking change to existing slots. Re-derivation on `clause_update` preserves them.
4. **Category C types (law-bench-only: capital_increase, insurance, merger_acquisition, ppp_project, private_equity_fund, trust, vam_agreement, software_development, ip_license, real_estate_development, film_production, talent_agency, equity_incentive, company_formation, land_transfer) are untouched** — the generator has no coverage for them.

## Capabilities

### New Capabilities
- `master-clause-rewrite`: required-element-driven 母版 completeness for Category A types + Category B new-type seeding + sub-type→tagged mapping
- `type-validation-constraints`: standalone legal hard-constraint table + draft compliance check (not in generation flow)
- `slot-instruction-enrichment`: prompt (大白话问法) + typed slots (enum/money/date/duration) merged into existing slot_instructions

### Modified Capabilities
- `clause-library`: ~24 Category A base sets supplemented; ~23 Category B types + base clauses added
- `tag-combinatorics`: new Category B types add scenario/stance combinations

## Impact

- **Code**: new `src/clauses/generator_import.py` (one-time YAML→DB importer reading `合同生成规则/contract_rules/rules/`); new `src/validations/` module (table model + load + `validate_draft`); `slot_instructions` derivation in `src/clauses/store.py` extended to accept/round-trip `prompt`+`type`; new MCP tools `validation_list` + `validation_check`.
- **Database**: NEW `type_validations` table; `clauses` gains supplemented base rows (Category A) + seeded base rows (Category B); `contract_types` gains ~23 rows; `slot_instructions` jsonb gains `prompt`/`type`/`enum_values` keys (no DDL — jsonb).
- **APIs**: 2 new MCP tools (`validation_list`, `validation_check`); existing `clause_update`/`create_clause` round-trip the new slot keys.
- **Dependencies**: none new — PyYAML already used by the engine; the generator's rules are vendored YAML.
- **Data**: ~24 base sets supplemented; ~23 new types seeded (~23 × ~8 base clauses ≈ 184 new base rows); all slot_instructions enriched with prompt+type; validation rows from ~30 generator `validation/*.yaml` files.
- **Re-eval**: `self_iterate` across the original 43 types MUST NOT regress below 39/43 all-pass; new Category B types baselined (no prior score to regress against).
