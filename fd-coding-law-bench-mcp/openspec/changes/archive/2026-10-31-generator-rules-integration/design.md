# Generator Rules Integration - Design

## Source: what the generator has, law-bench lacks

```
generator rule layer            law-bench today            action
─────────────────────────────────────────────────────────────────────
intent.yaml (type tree,         flat 43 types, no          (B) create ~23 missing
 线索驱动走门, param_doors)      sub-type leaves             types; sub-type leaves
                                                           → tagged scenarios

elements/ (要素卡:               slot_instructions has      (3) ADD prompt + type
 id/name/required/type/          name/label/example/         keys to slot_instructions
 prompt/大白话问法)              required/description        (jsonb, no DDL)

clauses/ ({{slot}} text +        clauses table IS the       (1) MERGE generator's
 topic dedup + source=民法典§)    same primitive ✓           required-driven 母版 +
 民法典-grounded review supplements; merge-not-replace

templates/ (stance_variants      stance concept exists ✓    (1) map to existing
 party_a/party_b)                                           stance override layer

validation/ (required/max/min/   NOTHING — eval rubric      (2) NEW type_validations
 max_duration/regex/oneof/        checks completeness,       table; standalone draft
 always, severity error/warning)  not legal hard limits      compliance check, NOT
                                                           in assembly/fill/self-heal
```

## Type mapping (the scope that splits "rewrite" vs "new")

### Category A — rewrite/supplement (~24 law-bench types, ~40 generator leaves)

Generator sub-type leaves collapse onto law-bench's flat types. Sub-type distinctiveness goes into `tagged` clauses with a `scenario` tag (the existing scenario filter already consumes these).

| generator family / leaves | law-bench key(s) | sub-type → tagged scenario |
|---|---|---|
| `sale.{movable,real-estate,vehicle}` | `sale`, `real_estate_sale` | movable→sale base; real-estate→real_estate_sale; vehicle→sale tagged(scenario=车辆买卖) |
| `lease.immovable.{house,shop,office,warehouse,parking}` | `lease`, `real_estate_lease` | house→real_estate_lease base; shop/office/warehouse/parking→lease tagged(scenario=…) |
| `lease.movable.vehicle`, `lease.equipment.{computer,printer,construction,phone}` | `lease` | each→lease tagged(scenario=车辆/电脑/打印机/建筑设备/手机租赁) |
| `lease.financing` | `financing_lease` | 1:1 |
| `loan.{civil,financial}` | `loan` | civil→base; financial→tagged(scenario=金融借款) |
| `transport.{freight,passenger,multimodal}` | `transport` | freight→base; passenger/multimodal→tagged |
| `technology.{development,transfer,consulting,license}` | `technology`, `software_development`, `ip_license` | development→software_development; license→ip_license; transfer/consulting→technology tagged |
| `project.{construction,survey,design}` | `construction` | construction→base; survey/design→tagged |
| `work.{processing,custom,repair,decoration}` | `work` | processing→base; custom/repair/decoration→tagged |
| `labor` | `employment` | 1:1 |
| `gift` `mandate` `brokerage` `consignment` `partnership` `guarantee` `factoring` `property` `service` `utility` `deposit` `storage` | `gift` `entrustment` `intermediation` `brokerage` `partnership` `guarantee` `factoring` `property_service` `service` `utilities_supply` `bailment` `warehousing` | 1:1 × 12 |
| `equity-transfer` `franchise` `nominee-holding` `labor-dispatch` `tourism` | `equity_transfer` `franchise` `equity_holding_in_trust` `labor_dispatch` `tourism_service` | 1:1 × 5 |

### Category B — new types (~23, generator-only)

law-bench has no `contract_type` row. Create the type + seed base clauses from the generator's `clauses/<type>.yaml`.

| group | generator types |
|---|---|
| 担保物权 | `mortgage`, `pledge` |
| 婚姻家事继承 | `will`, `prenup`, `marital-property`, `divorce`, `adoption`, `legacy-support`, `elderly-support`, `estate-division` |
| 债与和解 | `debt-transfer`, `debt-restructuring`, `settlement`, `accident-settlement` |
| 用工劳务周边 | `nda`, `non-compete`, `internship`, `training`, `labor-service`, `housekeeping` |
| 商事 | `shareholders`, `investment`, `shop-transfer` |

### Category C — leave alone (law-bench-only, ~13)

`capital_increase` `company_formation` `equity_incentive` `film_production` `insurance` `merger_acquisition` `ppp_project` `private_equity_fund` `real_estate_development` `talent_agency` `trust` `vam_agreement` `land_transfer` `software_development`(partial). Generator has no coverage — untouched.

## Decision 1 — clause layering scheme ("怎么处理其他条款类型")

```
generator source                         law-bench slot
────────────────────────────────────────────────────────────────────
clauses/<family>.yaml                    source=base (母版)
   required elements define WHICH          required-element slots ⇒
   clauses every instance MUST have        mandatory; missing → 【待确认】
   (标的/付款/交付/违约… = the legal
    baseline skeleton)

clauses/<family>.<subtype>.yaml          source=tagged, scenario=<子类型>
   param-door leaves (房屋/商铺/车辆/       scenario-tagged; assembled on
   电脑/手机; sale 茶叶/肉牛/工业品)         stance/scenario match

templates/<clause>.yaml stance_variants  stance override (existing layer)
   party_a / party_b 文本变体               merge into tagged/stance

review-driven supplements                 source=tagged, legal_topic=…
   (优先承租权, 维修责任划分标准,             民法典-grounded enrichment
    自然损耗界定, 买卖不破租赁)              clauses, scenario=general
```

**Required-element → 母版 skeleton rule.** For each Category A type, the generator's `elements_for(type)` where `required:true` defines the mandatory clause set. If law-bench's existing base is *missing* one of those clauses, the generator's clause is merged in. If law-bench's base *already has* a richer clause on the same `topic`, the generator's text is NOT used as a replacement (merge-not-replace, per `sale-quanyi-override-drops-rich-base` memory) — only its `source`/`law_ref` citation may augment.

**Optional elements** (e.g. `签订日期`, `甲方证件号`, `免租期`) produce slots that render `【待确认：key】` when absent — they stay in the 母版 body as soft-fill, never block assembly.

## Decision 2 — `type_validations` (standalone, NOT in generation)

```sql
CREATE TABLE type_validations (
  id            SERIAL PRIMARY KEY,
  contract_type TEXT   NOT NULL,          -- FK contract_types.key
  constraint_id TEXT   NOT NULL,          -- e.g. lease_term_max
  kind          TEXT   NOT NULL,          -- required|max|min|max_duration|
                                          --   max_deposit_months|regex|oneof|always
  field         TEXT,                     -- which slot/element it constrains
  params        JSONB NOT NULL DEFAULT '{}',  -- {max: 20, unit: years} / {regex: …} / {values: […]}
  severity      TEXT   NOT NULL DEFAULT 'error',  -- error|warning
  law_ref       TEXT,                     -- 民法典§705
  inherited_from TEXT,                    -- type-tree level (for display)
  UNIQUE (contract_type, constraint_id)
);
```

Loaded once from the generator's `validation/*.yaml` (loader's `validations_for(type)` walks the inheritance chain; each constraint gets `inherited_from`).

**Compliance check (`validate_draft`) — runs against a finished draft, called explicitly:**
```
draft markdown / filled slots
        │
        ▼
type_validations[contract_type]  (inherited chain merged)
        │
        ▼
  ┌─────┴──────────────────────────────┐
  ▼                                     ▼
required: slot present & non-empty?     max/min/oneof/regex: value within bounds?
max_duration: months ≤ cap?             max_deposit_months: ≤ 3?
always: unconditional clause present?   (e.g. safety_termination §731)
  │
  ▼
{errors:[{constraint_id, message, law_ref, severity}],
 warnings:[…], passed: bool}
```

**Critically NOT called by:** `contract_generate`, `fill`, `self_heal_pipeline_run`, `auto_reject_pipeline_run`. Generation is unchanged. A new MCP tool `validation_check(contract_type, draft|slots)` invokes it; `validation_list(contract_type)` returns the constraints. This keeps the two concerns (generation vs legal compliance) independently evolvable — a validation rule change cannot break generation, and a generation change cannot silently bypass a legal limit.

## Decision 3 — `slot_instructions` enrichment (additive, no DDL)

Current slot_instructions entry (jsonb):
```json
{"name":"租金金额","label":"月租金","example":"3000元","required":true,"description":"每月租金金额"}
```
Enriched:
```json
{"name":"租金金额","label":"月租金","example":"3000元","required":true,
 "description":"每月租金金额",
 "prompt":"每个月租金是多少钱？","type":"money"}
```

- `prompt` — the generator's `elements[].prompt` 大白话问法, used by the extraction/drafting agent to ask the user in plain language.
- `type` — `text|money|date|duration|enum`; `enum` carries `enum_values:[…]` (from the generator's `type: enum{...}`). Lets the fill/extract step validate input shape (money parses to a number, duration to months, date to ISO, enum to a member).
- **Field-level inheritance** — the generator's `elements_for()` does a field-level merge where a deeper level redefines one field of a root element (loan redefines root `甲方(出租方)名称` → `甲方(出借人)名称` while inheriting `required`/`type`). In law-bench this is a per-type slot override: the `label`/`prompt` differs per `contract_type`, the `name` (slot key) stays constant so the same `{{party_a}}` placeholder works across types.
- `required:true` on slots aligns with generator's `required:true` elements — drives the 母版 skeleton (Decision 1).
- Re-derivation in `clause_update`/`create_clause` round-trips `prompt`/`type`/`enum_values` (currently only name/label/example/required/description are re-derived).

## Import mechanism

One-time importer `src/clauses/generator_import.py` (idempotent — keyed on `body_hash` + `contract_type` + `section`):
```
合同生成规则/contract_rules/rules/
   ├── intent.yaml      → contract_types rows (Category B new) + sub-type→scenario map
   ├── elements/        → slot_instructions enrichment (prompt+type) per type
   ├── clauses/         → base (Category A supplement + Category B seed) / tagged (scenario)
   ├── validation/      → type_validations rows
   └── templates/       → stance variant merge into tagged/stance layer
```
Re-runnable: existing rows matched by `body_hash` are skipped (not overwritten), so manual edits after import are preserved.

## Risks

- **Merge-not-replace violation.** Generator's sparse clause text overwrites law-bench's rich base → score regression. Mitigation: importer only ADDs missing-topic base clauses; existing base clauses keep their body, generator contributes only `source`/`law_ref`/`prompt`+`type`. Re-eval gate (39/43) catches any drop.
- **Category B types have no rubric / no prior eval baseline.** New types seed base clauses but start with no rubric — they're "draftable, not yet scored". Mitigation: import creates the type + base; rubric authoring is a follow-up (out of this change's scope — flagged in tasks).
- **Validation drift.** `type_validations` loaded once from YAML; if the generator's `validation/*.yaml` change, law-bench's copy is stale. Mitigation: importer is idempotent + re-runnable; record `imported_at` + `source_hash` per row so drift is detectable.
- **Slot name collisions across types.** Generator element ids are Chinese (`租金金额`); law-bench slot names are mixed (`party_a`, `amount`, CJK). Mitigation: importer maps generator element `id` → law-bench `{{slot}}` by matching `label`/`description`, falling back to CJK slot name (SLOT_PATTERN is Unicode-aware per `cjk-slot-names-and-coherence` memory). Conflicts logged, not silently overwritten.
- **Catalog count staleness.** `contract_type_catalog` without `refresh:true` returned 0 clauses for all types (proven stale — `clause_list(sale)` returns 1278 tagged). Always `refresh:true` before scoping import work to avoid misjudging library richness.
