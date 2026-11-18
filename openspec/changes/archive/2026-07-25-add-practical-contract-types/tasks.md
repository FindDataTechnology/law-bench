## 1. Practical-type rubrics

- [x] 1.1 Append 22 `_rubric(type_key, description, [criteria])` entries to `RUBRICS` in `scripts/seed_contract_rubrics.py`, one per practical type, in this order with these type keys: `company_formation`, `equity_transfer`, `capital_increase`, `merger_acquisition`, `equity_incentive`, `vam_agreement`, `equity_holding_in_trust`, `real_estate_sale`, `real_estate_lease`, `employment`, `labor_dispatch`, `ip_license`, `franchise`, `real_estate_development`, `insurance`, `trust`, `private_equity_fund`, `software_development`, `film_production`, `talent_agency`, `ppp_project`, `tourism_service`
- [x] 1.2 For each rubric, write 4-6 type-specific `_c(name, description, guidance)` criteria in Chinese (description = the check; guidance = `PASS if … / FAIL if …`), drawn from that type's governing statute (公司法 / 劳动法·劳动合同法 / 保险法 / 信托法 / 城市房地产管理法·商品房买卖司法解释 / 商业特许经营管理条例 / 旅游法 / 证券投资基金法·私募办法 / 著作权法·电影产业促进法 / PPP合同指南, etc.); reuse the existing `BASE_CRITERIA` unchanged as the first 4 criteria of every rubric
- [x] 1.3 Cite an exact article number only where well-established; otherwise have the criterion check clause presence/quality so the shared `legal_citation_accuracy` base criterion remains the accuracy gate
- [x] 1.4 Leave `BASE_CRITERIA`, `_c`, `_rubric`, and `main()` unchanged; confirm the printed count uses `len(RUBRICS)` (now 19 + 22 = 41) and the docstring's "19 per-class" wording is updated to reflect both sets
- [x] 1.5 Add a one-line docstring note that the D门类/K类 of 中国合同分类法 are not seeded (file incomplete)

## 2. Practical-type drafting prompts

- [x] 2.1 Append 22 `_p(type_key, description, content)` entries to `PROMPTS` in `scripts/seed_contract_prompts.py`, one per practical type, using the same 22 type keys as 1.1 in the same order
- [x] 2.2 For each prompt, write a Chinese `content` drafting instruction tailored to that type's mandatory clauses, mirroring the per-type rubric theme (1.2); set `contract_type = type_key`, `purpose = "drafting"`, `prompt_type = "baseline"` via the existing `_p` helper
- [x] 2.3 Leave `upsert_local_prompt`, `_p`, and `main()` unchanged; confirm the printed count uses `len(PROMPTS)` (now 19 + 22 = 41) and the docstring's "19 per-type" wording is updated to reflect both sets

## 3. zh/en display labels

- [x] 3.1 Add the same 22 type keys to `LABELS["zh"]["contract_type"]` in `src/web/i18n.py` with Chinese names (e.g. `company_formation` -> 公司设立合同, `equity_transfer` -> 股权转让合同, `employment` -> 劳动合同, `franchise` -> 特许经营（加盟）合同, `ppp_project` -> PPP项目合同, `tourism_service` -> 旅游服务合同)
- [x] 3.2 Add the same 22 type keys to `LABELS["en"]["contract_type"]` with English names (e.g. `company_formation` -> Company Formation, `equity_transfer` -> Equity Transfer, `employment` -> Employment, `franchise` -> Franchise, `ppp_project` -> PPP Project, `tourism_service` -> Tourism Service)
- [x] 3.3 Confirm the zh and en `contract_type` key sets are identical (parity required by `label_catalog_parity`); confirm `title_for_prompt`/`title_for_rubric` need no regex change (they already match `draft_<key>` / `contract_<key>_v1` and resolve `<key>` through the catalog)

## 4. Test update

- [x] 4.1 In `tests/test_i18n.py`, rewrite `test_label_catalog_has_19_contract_types` into `test_label_catalog_has_all_seeded_contract_types`: define `CIVIL_CODE_TYPES` (the 19 民法典 keys) and `PRACTICAL_TYPES` (the 22 practical keys) and assert `set(LABELS[locale]["contract_type"]) == CIVIL_CODE_TYPES | PRACTICAL_TYPES` for both `zh` and `en`
- [x] 4.2 Confirm no other test changes are needed (`tests/test_data_labels.py` and the rest use fixture-created `sale`/`draft_sale`/`contract_sale_v1` data, not the seeders - additive only)

## 5. Seed and verify

- [x] 5.1 Run `uv run python scripts/seed_contract_rubrics.py`; confirm 22 new `contract_<type>_v1` rubrics are upserted (42 local rubrics total: 19 民法典 + 22 practical + 1 sample) and harbor/eval rows are untouched
- [x] 5.2 Run `uv run python scripts/seed_contract_prompts.py`; confirm 22 new `draft_<type>` prompts are upserted (41 prompts total) and `rubrics`/`criteria` are untouched
- [x] 5.3 Run `uv run pytest tests/test_i18n.py tests/test_data_labels.py -q`; confirm green (zh/en parity holds, labels localize, unknown-value fallback still passes)
- [x] 5.4 Run `uv run pytest -q` (full suite); confirm green
- [x] 5.5 Verify DB counts: `sqlite3 db/evaluation_rules.db "SELECT COUNT(*) FROM rubrics WHERE source='local';"` -> 42; `SELECT COUNT(*) FROM prompts;` -> 41; spot-check one practical rubric has 4 base + 4-6 specific criteria and one practical prompt has `prompt_type='baseline'`
- [x] 5.6 Re-run both seeders once more; confirm idempotent (counts unchanged, no duplicates)
