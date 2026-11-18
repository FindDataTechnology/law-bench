## 1. Vocabulary + storage

- [x] 1.1 Add `src/clauses/tags.py`: `TAG_VOCAB` starting with the universal starter set `{stance: [pro_a, pro_b, balanced], strength: [strong, standard, mild], risk: [high, medium, low], mandatory: [mandatory, default, recommended]}`; `register_tag_dim(name, values)` (review-gate grower); `validate_tags(tags) -> dict` (drop unknown keys; raise `ValueError` on known-key/unknown-value); `normalize_tags` for safe reads
- [x] 1.2 Register the employment-specific dims proposed by the pilot: `special_restriction_period ∈ {probation, service_period, non_compete, declassification, none}`, `working_hours_system ∈ {standard, comprehensive, flexible, part_time}` (via `register_tag_dim`)
- [x] 1.3 Add `tags JSONB NOT NULL DEFAULT '{}'::jsonb` to `clauses` via `_ADDITIVE_COLUMNS` in `src/eval/store.py`; include `tags` in `_row_to_dict`
- [x] 1.4 Add `tags` to `_INSERT_COLS` + VALUES placeholders in `upsert_clause`/`upsert_clauses`/`create_clause`; `_row` emits `Jsonb(validate_tags(clause.get("tags") or {}))`; `update_clause` persists `tags` when supplied, else preserves existing
- [x] 1.5 Confirm `_finalize` does NOT touch `tags` (update docstring)

## 2. Store filters

- [x] 2.1 Extend `list_clauses`/`search_clauses` with optional `tags: dict | None = None`; append `tags->>'<dim>' = %s` per supplied dimension, composed with existing where-clauses
- [x] 2.2 Re-export `validate_tags`/`TAG_VOCAB`/`register_tag_dim` from `src/clauses/__init__.py`

## 3. Dashboard (create/edit/facets)

- [x] 3.1 `clause_new.html` + `clause_edit.html`: tag dropdowns driven by `TAG_VOCAB` (each with an empty "未标注" option); edit form pre-selects current tags
- [x] 3.2 `create_clause`/`update_clause` accept `tags` from form POST; validate via `validate_tags`
- [x] 3.3 `GET /clauses` + `GET /clauses/{type}` accept tag query params (`stance`/`strength`/`risk`/`mandatory` + any registered dim); map into the `tags` filter
- [x] 3.4 `clauses_list.html`/`clauses_detail.html`: tag-facet dropdowns in the toolbar; render each clause's tags as chips

## 4. Assembly by stance

- [x] 4.1 `generate_contract_assembled(..., stance: str | None = None)`: when set, filter the custom-clause selection to `tags->>'stance' = stance` (base/tagged unchanged)
- [x] 4.2 CLI `python -m src.clauses generate <type> [--province ...] [--custom ...] [--stance pro_a|pro_b|balanced]`
- [x] 4.3 Web `GET /clauses/{type}/generate?...&stance=pro_a` passes stance through

## 5. Per-type seed manifest + loader

- [x] 5.1 Define the manifest schema (`src/clauses/seed_manifest.py`): `data/clause_seeds/<contract_type>.yaml` = `{tags: [{name, values}], clauses: [{family, section, body, slots?, law_refs?, stance?, strength?}], skipped: [{item, reason}]}`; a `load_manifest(path)` + `validate_manifest`
- [x] 5.2 Author `scripts/seed_stance_clauses.py [--type <key>]`: read manifest(s); `DELETE FROM clauses WHERE source_doc_title = 'seed:<contract_type>'`; then `create_clause` each (idempotent); `manual=true`; set each clause's `tags` from the manifest
- [x] 5.3 Run + verify via `count_clauses`/`list_clauses("employment", category="custom", tags={"stance":"pro_a"})`

## 6. Per-type analyze -> evaluate -> decide run

- [x] 6.1 Author `data/clause_seeds/employment.yaml` from the completed pilot (Kimi): 2 type-specific tag dims, 4 clauses (§22 / §23-24 / §39+503号 / §4), 4 skipped with reasons
- [x] 6.2 For each remaining contract_type (40): A (consult Kimi, type-specific, no 大路货) -> B (evaluate 《法条》 real & current; non-redundant with base; real signal) -> C (add real / record skipped) -> write `data/clause_seeds/<type>.yaml`. All 40 succeeded (186 clauses, 132 tag dims, 188 skips).
- [x] 6.3 Spot-check each manifest's 《法条》 for realness - agents verified via dataPro and flagged 35 clauses `verdict: unverified` (wrong/uncertain article numbers kept verbatim, NOT fabricated)
- [x] 6.4 Coverage index `data/clause_seeds/INDEX.md` written: per-type added/skipped/unverified counts
- [x] 6.5 Legal review of the 35 `unverified`-法条 clauses - DONE via 4 parallel subagents + dataPro: corrected wrong article numbers (e.g. 公司法§147->§180, §57->§86, §32->§86, 优先认购权->§227, 信托法§44/§50->§48/§10, 仓储§910->§912, §913->§903, 旅游法§70->§81, 电影§16->§17, PPP§30->§41); confirmed correct ones (融资租赁§741, 利率规定§25, 供电营业规则§79, 国资法§55, §577); marked 合同约定 for commercial terms with no statute. 0 unverified remain.
- [x] 6.6 Normalize literal `{{slot}}` -> named slots + add `slot_instructions` per clause - DONE via 6 parallel subagents: 57 literal `{{slot}}` -> contextual names (canonical-preferred), 1 `{{article_num}}` -> 公司法§47, 180 `slot_instructions` authored across 125 slotted clauses; 0 literal `{{slot}}` remain, 0 coverage failures (every body slot has a matching instruction), all yaml valid. 61 slot-less clauses need none.

## 7. Tests

- [x] 7.1 `tests/test_clauses_tags.py`: vocab validation (known/unknown values; unknown key dropped; `ValueError` on bad value); `register_tag_dim` grows vocab; `_row`/`create_clause`/`update_clause` persist tags; body-edit preserves tags; `list_clauses` tag filter composes
- [x] 7.2 `tests/test_clauses_seed_manifest.py`: manifest load/validate (bad 法条 field, missing section, unknown stance rejected); loader idempotent (run twice -> no dup); loader sets `tags` + `manual=true`
- [x] 7.3 `tests/test_clauses_assemble_stance.py`: `generate_contract_assembled(..., stance="pro_a")` includes only `pro_a` custom clauses (base/tagged unchanged); `stance=None` behaves as today; unknown type still raises `NotFoundError`
- [x] 7.4 `tests/test_clauses_admin_web.py`: create/edit persist tags; browse `?stance=pro_a` filters; facets + chips render
- [x] 7.5 Run `uv run pytest tests/test_clauses_*.py` - all pass, no regression

## 8. Verification

- [x] 8.1 `uv run python -c "from src.clauses import validate_tags, TAG_VOCAB, register_tag_dim; print('ok')"`
- [ ] 8.2 Manual: `seed_stance_clauses.py --type employment` -> browse facets -> assemble `--stance pro_a` -> confirm a 偏甲方 employment contract body
- [ ] 8.3 `uv run uvicorn src.web.app:app --port 8010` -> tag dropdowns on create/edit; facet browse; stance-generate download
- [x] 8.4 `openspec validate add-clause-custom-tags` -> valid
- [x] 8.5 Coverage index check: every one of the 41 contract types has a manifest entry (added or explicitly skipped)
