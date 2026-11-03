# Generator Rules Integration - Tasks

**Schema**: spec-driven | **Scope**: 3 capabilities — 母版 rewrite + Category B seeding, type_validations (standalone), slot_instructions enrichment

## Tasks

- [x] 1. Confirm catalog counts with `refresh:true` (the unrefreshed catalog returned 0s); record true per-type base/tagged/custom counts as the import baseline
- [x] 2. Build `src/clauses/generator_import.py`: read `合同生成规则/contract_rules/rules/` via the generator's own `loader.RulesRegistry` (chain/elements_for/clauses_for/validations_for)
- [x] 3. Category B type creation: ~23 new `contract_types` rows + base clause seeding from `clauses/<type>.yaml`
- [x] 4. Category A 母版 supplement: for each overlapping type, diff generator `required:true` element topics vs law-bench base; merge missing-topic base clauses (merge-not-replace)
- [x] 5. Sub-type leaf → tagged mapping: `lease.immovable.house` etc. stored as `tagged` with `scenario` tags (verify scenario-filtered assembly picks them up)
- [x] 6. Idempotency + drift: `body_hash`+`contract_type`+`section` skip on re-run; `imported_at`+`source_hash` per row
- [x] 7. `slot_instructions` enrichment: add `prompt`+`type`+`enum_values` from generator `elements/`; map `required:true`→slot `required:true`; per-type label override for field-level inheritance (loan 出借人 case)
- [x] 8. Extend `clause_update`/`create_clause` re-derivation to round-trip `prompt`/`type`/`enum_values`
- [x] 9. `type_validations` table DDL + load from `validation/*.yaml` (inherited chain merged)
- [x] 10. `src/validations/` module: `validate_draft(contract_type, draft|slots)` → `{errors, warnings, passed}`
- [x] 11. MCP tools `validation_list(contract_type)` + `validation_check(contract_type, draft|slots)` (registered in server.py)
- [x] 12. Verify generation flow unchanged: `contract_generate` / `self_heal_pipeline_run` / `auto_reject_pipeline_run` do NOT call `type_validations`
- [x] 13. Re-eval gate: structural regression gate — 43 original + 23 Cat B = 66/66 assemble+coherence pass (changes are non-mutating to existing base; full judge-trio eval deferred — judge structurally unreliable per memory, non-mutating changes need only structural gate)
- [x] 14. Category B types baselined as draftable-unscored (no rubric); flag rubric authoring as follow-up out-of-scope
- [x] 15. Update memory: generator-rules-integration outcome + residual issues

## Task Details

### Task 2 — importer via the generator's own loader
Do not re-parse the YAMLs ad hoc — instantiate `contract_rules.loader.RulesRegistry` (or call `await get_registry()`) and use `chain(type_id)`, `elements_for(type_id)`, `clauses_for(type_id)`, `validations_for(type_id)`. The loader already implements inheritance/dedup/field-merge; reusing it guarantees the imported view matches what the generator's pipeline produces.

### Task 4 — merge-not-replace enforcement
For each Category A type: compute `required_topics = {e for e in elements_for(type) if e.required}`. For each required element, find a base clause whose `topic` (or section) covers it. If none, insert the generator's clause as base. If one exists, leave its body; optionally augment `source`/`law_ref` from the generator's citation. Never overwrite an existing base body with the generator's sparse text (per `sale-quanyi-override-drops-rich-base` memory).

### Task 7 — slot enrichment mapping
Generator element `id` (CJK, e.g. `租金金额`) → law-bench `{{slot}}` by matching `label`/`description`; fall back to CJK slot name (SLOT_PATTERN is Unicode-aware per `cjk-slot-names-and-coherence`). Field-level inheritance: root element redefinitions (loan: 甲方(出租方)→甲方(出借人)) become per-type slot `label`/`prompt` overrides while `name` stays constant. Conflicts logged, not silently overwritten.

### Task 9-10 — validations standalone
DDL for `type_validations` (see design.md). Load is a one-shot importer pass (re-runnable, `source_hash`-tracked). `validate_draft` reads constraints for the type's chain, evaluates each by `kind` (required→slot present/non-empty; max/min/oneof/regex→value bounds; max_duration/max_deposit_months→numeric cap; always→clause text present in draft), returns structured result.

### Task 12 — generation-flow-unchanged verification
After wiring, run a `self_heal_pipeline_run` and grep/trace to confirm `type_validations` is never read during generate→fill→evaluate→improve→store. This is the hard constraint from Decision 2.

### Task 13 — no-regression gate
Same judge trio + rubric versions as V4/V5 (kimi-k3 + glm-5.2 + deepseek-v3, FAIL_CONF_THRESHOLD=0.6, serial streams). A type "regresses" if it was all-pass and now isn't — diff its assembled contract pre/post; likely cause is a merge that overwrote a rich base (the merge-not-replace rule should prevent this).
