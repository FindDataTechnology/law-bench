## 1. Schema: drop category/level; per-type tag_dims; tag_review

- [ ] 1.1 `tag_dims` -> `(contract_type, name, category, values, free_form, zh_label, description)` PK `(contract_type, name)`; migrate existing rows (universal -> `contract_type=NULL`, type-specific -> their type via manifest map); additive ALTER.
- [ ] 1.2 Add `clauses.tag_review JSONB DEFAULT '{}'::jsonb`; additive ALTER.
- [ ] 1.3 Drop `clauses.category` + `clauses.level` columns (additive `ALTER ... DROP COLUMN IF EXISTS`) - AFTER data migration (task 2) + code no longer uses them.

## 2. Data migration (category/level -> tags.source; tag_review)

- [ ] 2.1 Migrate existing clauses: `tags.source = category`; `tag_review = {dim: approved}` for curated (manual/seed) tags, `{dim: pending}` for none/auto. (One-off script against the DB.)
- [ ] 2.2 Backfill `tag_dims.category` for existing dims (source->来源, stance/strength->利益倾向, risk/mandatory->风险合规, region->地域, type-specific->类型专属).
- [ ] 2.3 Seed `source` dim (universal, 来源, [base,tagged,custom]) into tag_dims.

## 3. tags.py: per-type vocab + categories + governance

- [ ] 3.1 `TAG_VOCAB` -> per-type: `{contract_type: {dim: values}}` (NULL=universal); `load_vocab_from_db()` builds it; `FREE_FORM_TAGS` per-type aware.
- [ ] 3.2 `validate_tags(tags, contract_type)`: check universal (NULL) + that type's dims; free-form dims accept any string; drop unknown; raise on bad value.
- [ ] 3.3 `register_tag_dim(contract_type, name, category, values, free_form, zh_label)`: reuse-or-create (merge values if exists).
- [ ] 3.4 Category constants + helpers (`TAG_CATEGORIES`).

## 4. store.py: drop category/level; tags.source; per-type validate

- [ ] 4.1 Remove `category`/`level` from `_INSERT_COLS`/`_row`/`_row_to_dict`/ON CONFLICT; `_row` sets `tags.source` from the clause's source field + derives level for assembly (or drop level entirely).
- [ ] 4.2 `validate_tags(tags, contract_type)` in `_row` (needs `clause["contract_type"]`).
- [ ] 4.3 `list_clauses`/`search_clauses`: filter by `tags.source` (replaces `category=`), `tags.region`, any tag dim; remove the `category` param (use `tags={"source":...}`).
- [ ] 4.4 `counts_by_type`: group by `tags.source` (not `category`); provinces from `tags.region`.
- [ ] 4.5 `create_clause`/`update_clause`: no category/level; `tags` includes source; `tag_review` set on create (pending for auto, approved for manual?).

## 5. extract.py: auto-tag

- [ ] 5.1 Extraction prompt: add a `tags` field per clause suggesting `stance/strength/risk/mandatory`; `source` from doc level (base/tagged); `region` from province (already).
- [ ] 5.2 `_post_process`: build `tags` (source + region + LLM-suggested universal) + `tag_review` (all pending).
- [ ] 5.3 `validate_tags(tags, contract_type)` on the extracted clauses.

## 6. Tag review (tag_review)

- [ ] 6.1 `src/clauses/tag_review.py`: `review_tag(clause_id, dim, status)`, `bulk_review(clause_id, status)`, `is_assembly_ready(clause)` (all set dims approved).
- [ ] 6.2 `list_clauses(..., review_status=...)` filter (pending/approved/rejected).
- [ ] 6.3 Review routes: `POST /clauses/{type}/clauses/{id}/review` (per-dim), `POST .../review-all` (bulk); audit dashboard `GET /clauses/review` (pending backlog, coverage).

## 7. assemble.py: assembly by tags

- [ ] 7.1 `generate_contract_assembled(contract_type, tags={...})`: base (`tags.source=base`) + tagged (`tags.source=tagged ∧ tags.region=X`) + custom (`tags.source=custom ∧ tags match ∧ is_assembly_ready`).
- [ ] 7.2 `tags` filter: multi-dim (source/region/stance/strength/...). CLI `--tags dim:val,dim:val`; web `?tag=dim:val`.
- [ ] 7.3 Keep `province`/`stance` params as thin aliases (map to tags) for backward compat, or remove.

## 8. Dashboard UI

- [ ] 8.1 Create/edit form: tag dropdowns grouped by category; `source` dim (base/tagged/custom); region text field; type-specific dims (from the type's vocab).
- [ ] 8.2 Review UI: pending backlog list; per-dim approve/reject; bulk-approve; audit (coverage/distribution).
- [ ] 8.3 Assembly page: category-grouped tag pickers -> assemble + download.
- [ ] 8.4 Browse: facets by category (source/region/stance/...).

## 9. seed_manifest.py + seeder governance

- [ ] 9.1 `seed_tag_dims`: register each manifest's dims with `contract_type=<type>` + `category=类型专属` via `register_tag_dim` (reuse-or-create).
- [ ] 9.2 `clause_to_record`: `tags.source=custom`; `tag_review={dim: approved}` (curated seeds are approved).
- [ ] 9.3 Universal dims seeded with `contract_type=NULL`.

## 10. Tests + verify

- [ ] 10.1 `test_clauses_tags.py`: per-type validate, categories, register reuse-or-create, free-form.
- [ ] 10.2 `test_clauses_tag_review.py`: review per-dim + bulk, is_assembly_ready, list filter.
- [ ] 10.3 `test_clauses_assemble.py`: assembly by tags (source/region/stance), only approved custom.
- [ ] 10.4 `test_clauses_extract.py`: auto-tag (source/region/stance suggested, tag_review pending).
- [ ] 10.5 Update existing clause tests for category->tags.source.
- [ ] 10.6 Run full clause suite; `openspec validate unify-clause-tags`.
- [ ] 10.7 Deploy: migrate DB -> deploy code -> drop columns -> verify live.

## 11. Verification

- [ ] 11.1 Import check; manual: assemble by tags; review flow; audit dashboard.
- [ ] 11.2 `openspec validate unify-clause-tags` valid.
