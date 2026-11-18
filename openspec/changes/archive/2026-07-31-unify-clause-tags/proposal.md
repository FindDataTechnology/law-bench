## Why

Clause classification is split across **three separate columns** (`category` base/tagged/custom, `level` national/local, `province` region) **plus** the `tags` JSONB (stance/strength/risk/mandatory/region/type-specific). This is inconsistent - region was already moved into `tags`, but `category`/`level` are still columns, and the tag vocabulary is a flat global set (`tag_dims(name PK)`) shared across all contract types. The consequences:

- "母版 (base)" and "区域特色 (tagged)" are not tags - they're a separate `category` column, so they can't be filtered/assembled like other tags.
- The tag vocabulary is global: two contract types that happen to define a dim with the same name collide (merged values), and a type can't independently evolve its tag dims.
- There is no tag review: auto-suggested or manually-set tags go straight into assembly with no quality gate.
- Tag dims proliferate without governance - nothing stops creating `non_compete_type` when `special_restriction_period` already exists.

This change unifies **all** clause classification into `tags`, makes the vocabulary per-contract-type (decoupled), groups dims into categories, adds a review workflow (per-dim + bulk), auto-tags at extraction, and governs dim creation (reuse existing, else create new). Assembly then selects clauses by any tag combination (source/region/stance/...).

## What Changes

- **`category`/`level`/`province` columns -> tags.** `tags.source` (base/tagged/custom) replaces `category`; `level` is derived (base=national, tagged=local); `province` already moved to `tags.region`. The three columns are dropped. Every classification dimension is a tag.
- **Per-type tag vocabulary.** `tag_dims(contract_type, name, category, values, free_form, zh_label)` with PK `(contract_type, name)`. Universal dims (source/region/stance/strength/risk/mandatory) have `contract_type=NULL` (shared); type-specific dims have `contract_type=<key>` (decoupled per type). `validate_tags(tags, contract_type)` checks against that type's vocab.
- **Tag categories.** Each dim has a `category` (来源/利益倾向/风险合规/地域/类型专属). The dashboard groups dims by category; assembly UI picks by category.
- **Tag governance (reuse-or-create).** `register_tag_dim(contract_type, name, ...)` reuses an existing dim (merges values) or creates a new one. The seeder, extraction, and manual entry all go through this so dims don't proliferate.
- **Auto-tag at extraction.** The extraction LLM also suggests universal tags (stance/strength/risk/mandatory); `source` is set from the doc's level (base/tagged); `region` from the inferred province. Auto-suggested tags enter `tag_review` as `pending`.
- **Tag review (two granularities).** `clauses.tag_review` JSONB `{dim: pending|approved|rejected}` stores per-dim review status. A clause is "assembly-ready" when every set dim is `approved`. The UI supports per-dim review AND bulk-approve-all.
- **Assembly by tags.** `generate_contract_assembled(contract_type, tags={...})` selects base (`tags.source=base`) + tagged (`tags.source=tagged ∧ tags.region=X`) + custom (`tags.source=custom ∧ tags match ∧ all dims approved`). CLI/web gain `--tags dim:val` / `?tag=dim:val`.
- **No changes** to the clause body/slot/law_ref model, document generation, or contract templates.

## Capabilities

### New Capabilities
- `unify-clause-tags`: all clause classification is tags (source/region/stance/...), per-type vocab with categories, tag review (per-dim + bulk), tag governance (reuse-or-create), auto-tag at extraction, and assembly by any tag combination.

### Modified Capabilities
- `clause-knowledge-base` / `clause-admin` / `clause-custom-tags`: category/level/province columns dropped; store/assemble/extract/web use `tags.source`/`tags.region`; tag vocab per-type; review workflow.

## Impact

- **New code**: `src/clauses/tag_review.py` (review helpers); review routes/templates; assembly `tags` filter; governance in `tags.py`.
- **Modified code**: `src/eval/store.py` (drop category/level/province from schema + additive DROP); `src/clauses/store.py` (no category/level/province; `tags.source`; validate_tags per-type); `src/clauses/extract.py` (auto-tag + source/region); `src/clauses/assemble.py` (assemble by tags); `src/clauses/tags.py` (per-type vocab, categories, governance); `src/clauses/seed_manifest.py`; `src/web/routes/clauses.py` + templates (review UI, category-grouped assembly).
- **Data migration**: `category`/`level`/`province` -> `tags.source`/derived/`tags.region`; `tag_dims` gains `contract_type` + `category` (backfill universal dims with NULL, type-specific with their type); `clauses.tag_review` added (existing curated tags -> approved; auto-tags -> pending).
- **Dependencies**: none new.
- **Out of scope**: tag value normalization (京/北京), tag conflict detection, role-based review auth, the optional `业务场景` category.
