## 1. Corpus analysis -> per-type `scenario` vocabulary

- [x] 1.1 For each contract type with multi-region extraction, enumerate sub-types from the `当事人`/`标的` sections (start with `sale`, `service`, `real_estate_lease`, `entrustment`, `property_service`, `construction`); record the proposed `scenario` values per type
- [x] 1.2 For low-variation types (1 region / homogeneous), decide a minimal vocab (`其他` + any obvious split) so the dimension is uniform across types
- [x] 1.3 Add a `scenario` entry to each type's `tags[]` in `data/clause_seeds/<type>.yaml` (category `业务场景`) with the enumerated values; re-run `seed_tag_dims` and confirm rows

## 2. Add the `scenario` dimension

- [x] 2.1 `src/clauses/tags.py`: document `scenario` as a per-type controlled dim (category `业务场景`); ensure `validate_tags`/`normalize_tags` check it against `TAG_VOCAB[contract_type]['scenario']`
- [x] 2.2 `src/clauses/seed_manifest.py`: confirm `seed_tag_dims` loads `scenario` from manifests like any type-specific dim; add `scenario` to the universal-dim exclusion list (it is per-type, not universal)

## 3. Drop `region` (province)

- [x] 3.1 `src/clauses/tags.py`: remove `region` from `FREE_FORM_TAGS` and the universal seed in `seed_tag_dims`
- [x] 3.2 `src/clauses/store.py`: remove the "strip `region` for national/base" rule in `_row`; remove the `provinces`/region breakdown from `counts_by_type`
- [x] 3.3 `src/clauses/extract.py`: stop setting `clause_tags["region"]` (keep `province`/`level` inference only to derive `source`)
- [x] 3.4 `src/web/routes/clauses.py` + `clauses_detail.html`, `clauses_list.html`, `clause_new.html`, `clause_edit.html`: remove the region filter and region field; remove region display

## 4. Auto-tag `scenario` at extraction

- [x] 4.1 `src/clauses/extract.py`: extend the extraction prompt to suggest `scenario` per clause (from body/parties/标的); set `clause_tags["scenario"]` when present
- [x] 4.2 Ensure auto-tagged `scenario` enters `tag_review` as `pending` (same path as `stance`/`strength`); `tag_review.py` needs no change but add a test asserting `scenario` is pending after extraction

## 5. Assembly by `scenario`

- [x] 5.1 `src/clauses/assemble.py`: replace the `province` parameter with `scenario` on `generate_contract_assembled`; select `source=tagged` clauses where `tags.scenario == scenario`
- [x] 5.2 `src/clauses/assemble.py`: change output naming to `<contract_type>__<scenario>.<ext>` (drop `__province`); keep `<contract_type>.<ext>` when no scenario
- [x] 5.3 `src/clauses/cli.py`: update `--tags dim:val` / province CLI surface to `scenario`

## 6. MCP tool: `scenario` recognition

- [x] 6.1 `fd-coding-law-bench-mcp/.../tools/generate.py`: derive `scenario` from `tags["scenario"]` (drop `tags["region"]`/`tags["province"]`); pass `scenario=` to `generate_contract_assembled`
- [x] 6.2 Update the tool docstring: `tags` recognizes `stance` and `scenario`; `region`/`province` are ignored
- [x] 6.3 Update `test_generate_tool.py`: assert `tags={"scenario":...}` filters tagged clauses; `tags={"region":...}` is ignored

## 7. Web: `scenario` filter + display

- [x] 7.1 `src/web/routes/clauses.py`: add a `scenario` filter param + `scenarios` collection (distinct `tags.scenario` per type) to the detail route
- [x] 7.2 `src/web/templates/clauses_detail.html`: add a `scenario` filter `<select>`; show `scenario` on clause cards
- [x] 7.3 `clauses_list.html`, `clause_new.html`, `clause_edit.html`: add `scenario` display/entry (controlled dropdown from the type's vocab)

## 8. Retag corpus + migration

- [x] 8.1 Write a one-time classify-only retag job: run the LLM over existing clause bodies to assign `tags.scenario` (pending review), batched per type
- [x] 8.2 Migration SQL: `UPDATE clauses SET tags = tags - 'region', tag_review = tag_review - 'region'` (drop province); leave `scenario` from the retag
- [x] 8.3 Document the migration in the deploy/runbook note (ship code, run retag + migration, bulk-approve per type)

## 9. Tests & verification

- [x] 9.1 Update assemble tests: `generate_contract_assembled` takes `scenario=` (not `province`); tagged selection filters by `tags.scenario`; file name uses `__scenario`
- [x] 9.2 Update extract tests: extracted clauses carry `tags.scenario` (pending) and no `tags.region`
- [x] 9.3 Update store tests: `counts_by_type` reports `scenarios` (not `provinces`); base clauses no longer have `region` stripped
- [x] 9.4 Run the full suite (`pytest`) + manifest validation; confirm green
- [ ] 9.5 Manual smoke: `generate_contract_from_tags(contract_type="sale", tags={"scenario":"建材工业品"})` returns a scenario-filtered contract; `tags={"region":"广东"}` is ignored
