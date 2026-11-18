## Context

The eval + generation system stores, per Chinese contract type, three linked artifacts: a `contract_<type>_v1` rubric (in `rubrics`/`criteria`), a `draft_<type>` drafting prompt (in `prompts`), and zh/en display labels (in `src/web/i18n.py::LABELS["contract_type"]`). Today this covers only the 19 《民法典》典型有名合同 (Part 1 of `chinese_contracts_class.md`): 20 local rubrics + 19 prompts in `db/evaluation_rules.db`, seeded idempotently by `scripts/seed_contract_rubrics.py` and `scripts/seed_contract_prompts.py`.

`chinese_contracts_class.md` Part 2 describes the "中国合同分类法" 实务体系 (法天使) - a practical taxonomy with four 一级门类 (A 公司股权 / B 常见法律关系 / C 特定行业 / D) plus a K 附属类. None of it is seeded. Many Part 2 sub-types duplicate the 民法典 19 (买卖/租赁/借款/担保/委托/建设工程/运输/保管/仓储/融资租赁/合伙…); the rest are genuinely new practical/industry types governed by special laws (公司法, 劳动合同法, 保险法, 信托法, 城市房地产管理法, 商业特许经营管理条例, 旅游法…). The file is also incomplete: Part 2 is cut off mid-category C (at 旅游); D门类 and K类 have no details.

Constraints: the seed scripts upsert by `name` (UNIQUE) and are the established pattern; `src/web/i18n.py` enforces zh/en label parity (`label_catalog_parity`, asserted by `tests/test_i18n.py`); `title_for_prompt`/`title_for_rubric` derive display titles from the `draft_<key>` / `contract_<key>_v1` name convention + the label catalog, so no regex change is needed for new keys; no test runs the seeders (the suite uses fixture-created rows).

## Goals / Non-Goals

**Goals:**
- Add a curated, non-overlapping set of ~22 Part 2 practical contract types to the rubric, prompt, and label catalogs, so practical/industry contracts can be drafted, evaluated, and compared type-specifically.
- Reuse the existing seed/schema/label pattern verbatim - no schema change, no new module, no crew change.
- Keep the 19 民法典 types and all existing rows untouched; re-seeding remains idempotent.
- Keep zh/en label parity and the existing test suite green (one test rewritten, rest additive).

**Non-Goals:**
- Seed the ~10 Part 2 sub-types that 1:1 duplicate the 民法典 19 (no redundant rubrics/prompts).
- Infer or seed the missing D门类 / K类 (file has no details).
- Add per-type `templates/*.md` (the 19 民法典 types have none either; the drafter loads the 2 shared reference templates via `_templates_reference()`).
- Change the generation crew (`src/crew.py`, `config/*.yaml`) - contract type is inferred by the intake agent from the user request; the new prompts are consumed by the compare flow, not hardcoded.
- Formalize the data-label `LABELS` catalog as a new web-i18n requirement (it is un-specced today; this change only grows its data, not its behavior).

## Decisions

**D1 - Curate ~22 non-overlapping practical types, not all ~30 sub-types.**
The 22 types (A门类 7 / B门类 6 / C门类 9) are the Part 2 sub-types that are *not* 1:1 duplicates of a 民法典 type and that carry distinct mandatory-clause sets. *Alternatives considered:* (a) seed all ~30 二级分类 including overlaps -> rejected, creates redundant rubrics/prompts for 买卖/租赁/etc. and confuses the compare flow; (b) seed only the 4 一级门类 -> rejected, too coarse for per-type rubrics and D is missing from the file. The 22-type list is in `tasks.md` and the proposal Impact.

**D2 - Borderline-overlap types kept as distinct.**
`real_estate_sale`, `real_estate_lease`, and `software_development` are conceptually adjacent to 民法典 买卖/租赁/技术合同 but are kept, because each is governed by a distinct special law with distinct mandatory clauses not covered by the generic 民法典 rubric (不动产登记/预售许可/过户; 登记备案/买卖不破租赁; 软件交付验收/知识产权归属). The ~10 true duplicates (民间借贷, 担保/保证, 委托, 中介, 行纪, 保管仓储, 建设工程细分, 物流运输, 公用事业, 融资租赁, 合伙协议) are skipped.

**D3 - Reuse the existing seed helpers; no schema or module change.**
Each new rubric is appended to `RUBRICS` via the existing `_rubric(type_key, desc, [criteria])` (= 4 shared `BASE_CRITERIA` + type-specific `_c(...)`); each new prompt via `_p(type_key, desc, content)`. `main()` uses `len(RUBRICS)`/`len(PROMPTS)`, so counts auto-update. *Alternative:* a new `seed_practical_contract_*.py` -> rejected, fragments the catalog and the spec's "one idempotent seeder" expectation; the existing scripts already seed a registry of per-type rows and growing that registry is the established pattern.

**D4 - Type-specific criteria cite each type's governing statute, not just 民法典.**
The 4 shared base criteria (`party_identification`, `governing_law_present`, `clause_completeness`, `legal_citation_accuracy`) are reused unchanged - they apply to every contract type. The 4-6 type-specific criteria per rubric are drawn from the type's governing statute (e.g. employment -> 劳动合同法 试用期/解除/经济补偿; insurance -> 保险法 如实告知/免责/理赔; franchise -> 商业特许经营管理条例 备案/冷静期/信息披露). Criteria describe the *clause to check* and a `PASS if … / FAIL if …` guidance, mirroring the 民法典 rubrics. Where an exact article number is uncertain, the criterion checks clause presence/quality rather than citing a specific number, so the base `legal_citation_accuracy` criterion remains the accuracy gate.

**D5 - Labels: 22 keys added to both `zh` and `en`; derivation auto-handles them.**
`LABELS["zh"]["contract_type"]` and `LABELS["en"]["contract_type"]` each gain the same 22 keys (parity). `title_for_prompt`/`title_for_rubric` already match `draft_<key>` / `contract_<key>_v1` and resolve `<key>` through the catalog, so no regex change. The exact-set test `test_label_catalog_has_19_contract_types` is rewritten to assert the catalog equals the 19 民法典 keys ∪ the 22 practical keys (renamed `test_label_catalog_has_all_seeded_contract_types`).

**D6 - D/K not inferred.**
Only A/B/C sub-types present in the file are seeded. The seeder docstrings flag the file gap so a future change can add D/K once sourced.

## Risks / Trade-offs

- **[Subjective curation]** The 22-type selection and the borderline-overlap calls (D2) are judgement calls. -> Mitigation: the skip list and the 22-type table are explicit in `tasks.md`/design; veto any type at review and it is dropped without affecting the others (each entry is independent).
- **[File incomplete]** D门类 and K类 are absent from `chinese_contracts_class.md`. -> Mitigation: do not infer; seed only what is present; flag in docstrings. A later change can extend.
- **[Re-seed overwrites UI edits]** Upsert-by-name means re-running a seeder overwrites a rubric/prompt edited through the UI. -> Existing trade-off (already documented in `seed_contract_prompts.py`); same behavior as the 19 民法典 types. No regression.
- **[Criteria legal precision]** Type-specific criteria reference special-law concepts; article numbers could be imprecise. -> Mitigation: criteria focus on clause presence/quality; the `legal_citation_accuracy` base criterion and the LLM judge remain the accuracy gate; numbers are cited only where well-established.
- **[Rollback is not automatic]** Reverting the script edits does not remove the 22 seeded rows (upsert does not delete). -> Rollback: delete the 22 `contract_<type>_v1` rubrics and 22 `draft_<type>` prompts by name, or drop the `contract_type` label keys. Documented in tasks verification.

## Migration Plan

1. Append the 22 rubric entries to `scripts/seed_contract_rubrics.py` and the 22 prompt entries to `scripts/seed_contract_prompts.py`; add the 22 zh/en label keys to `src/web/i18n.py`; rewrite the i18n exact-set test.
2. Run `uv run python scripts/seed_contract_rubrics.py` then `uv run python scripts/seed_contract_prompts.py` (idempotent upsert; local rows only, harbor/eval data untouched).
3. Run `uv run pytest tests/test_i18n.py tests/test_data_labels.py -q` (parity + labels) and verify DB counts (42 local rubrics = 19 民法典 + 22 practical + 1 sample; 41 prompts = 19 + 22).
4. **Rollback**: delete the 22 `contract_<type>_v1` rubrics + 22 `draft_<type>` prompts by name and revert the label/test edits.

## Open Questions

- Whether to source and add the D门类 and K类 in a follow-up (deferred - file is incomplete).
- Whether the borderline types (D2) should instead be folded into their 民法典 neighbor (decided: keep distinct; revisit if compare results show redundancy).
