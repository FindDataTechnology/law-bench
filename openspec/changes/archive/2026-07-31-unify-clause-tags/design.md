## Context

Built atop the clause KB + custom-tags + region-as-tag work:

- `clauses(id, contract_type, category base|tagged|custom, section, body, slot_instructions, law_refs, level national|local, source_path, source_doc_title, body_hash, manual, tags JSONB)` - `province` was already dropped (region moved to `tags.region`).
- `tag_dims(name PK, values JSONB)` - a flat global vocabulary; 4 universal starter dims + ~131 type-specific (loaded from manifests) + `region` (free-form). `FREE_FORM_TAGS={region}`. `load_vocab_from_db()` merges tag_dims into the in-memory `TAG_VOCAB` at app startup.
- `tags.py`: `validate_tags(tags)` (drops unknown keys, rejects bad values, free-form for region); `register_tag_dim(name, values)`; `TAG_VOCAB`.
- `store.py`: `_row` enforces category semantics (custom->null source_path, base->national+clear region, tagged->local); `list_clauses(tags=)` filters by `tags->>'dim'`; `counts_by_type` groups by `tags.region`.
- `extract.py`: `_post_process` sets `tags.region` from the inferred province; does NOT set other tags.
- `assemble.py`: `generate_contract_assembled(province=, stance=)` - base + tagged(region) + custom(stance). Only stance + region are assembly-relevant.
- No tag review: all tags (curated seed + manual) go straight to assembly.

User direction (2026-07-31): unify ALL classification into tags (including 母版/category), make the vocab per-contract-type (decoupled), categorize dims, auto-tag at extraction, review tags (both per-clause and per-dim granularity), and govern dim creation (reuse existing, else create new). Assembly selects by tag category combination; only custom is gated by review.

## Goals / Non-Goals

**Goals:**
- `category`/`level` -> `tags.source` (base/tagged/custom); drop the columns. `province` already -> `tags.region`.
- Per-type tag vocabulary: `tag_dims(contract_type, name, ...)`; universal dims shared (`contract_type=NULL`), type-specific decoupled.
- Tag categories (来源/利益倾向/风险合规/地域/类型专属) on each dim.
- Tag governance: `register_tag_dim` reuses existing (merge values) or creates new; seeder/extraction/manual all route through it.
- Auto-tag at extraction: LLM suggests universal dims; source/region set from the doc; enter `tag_review=pending`.
- Tag review: `tag_review` JSONB per-dim (pending/approved/rejected); assembly-ready = all set dims approved; UI supports per-dim + bulk.
- Assembly by tags: `generate_contract_assembled(tags={...})`; only custom gated by review.

**Non-Goals:**
- Tag value normalization (京 vs 北京) - deferred.
- Tag conflict detection (e.g. stance=pro_a but strength=mild contradictions) - deferred.
- Role-based review auth (who can approve) - deferred; trusted dashboard for v1.
- The optional `业务场景` category (B2B/B2C/行业) - follow-up.
- Re-tagging base/tagged in assembly (base/tagged are the backbone; only custom is tag-filtered + review-gated).

## Decisions

### D1: category/level -> tags.source; drop the columns
**Choice**: `tags.source ∈ {base, tagged, custom}` replaces the `category` column; `level` is derived (base=national, tagged=local, custom=null) and no longer stored; `province` already -> `tags.region`. The `clauses` table keeps only `tags` JSONB for classification.
**Rationale**: Consistent with the region-as-tag unification. "母版" and "区域特色" are classification labels, not special columns. Assembly filters by `tags.source` instead of `category=`.
**Alternatives**: Keep `category` column + mirror as `tags.source` (dual) - rejected (redundant, doesn't unify). Keep `level` - rejected (derivable from source).

### D2: Per-type tag vocabulary (decoupled)
**Choice**: `tag_dims(contract_type, name, category, values, free_form, zh_label)` PK `(contract_type, name)`. Universal dims (source/region/stance/strength/risk/mandatory) have `contract_type=NULL` (shared across all types). Type-specific dims have `contract_type=<key>`. `validate_tags(tags, contract_type)` checks universal + that type's dims.
**Rationale**: Different contract types can have a dim with the same name but different values/semantics; storing them separately (decoupled) lets each type's tag taxonomy evolve independently. Universal dims stay shared (avoid 43 redundant `stance` rows).
**Alternatives**: All dims per-type (including universal) - rejected (redundant universal rows). Keep global `tag_dims(name PK)` - rejected (type dim collisions, not decoupled).

### D3: Tag categories
**Choice**: `tag_dims.category` ∈ {来源, 利益倾向, 风险合规, 地域, 类型专属}. The dashboard groups dims by category; the assembly UI picks values per category.
**Rationale**: Categories group related dims for the UI + make "assemble by category" legible. The set is small + controlled.
**Alternatives**: No categories (flat) - rejected (harder UI, no grouping). Free-form categories - rejected (chaos).

### D4: Tag review - per-dim tag_review (supports both granularities)
**Choice**: `clauses.tag_review` JSONB `{dim: pending|approved|rejected}`. A clause is "assembly-ready" when every dim in its `tags` has `tag_review[dim]=approved`. The UI supports per-dim approve/reject AND bulk-approve-all (sets all dims approved).
**Rationale**: Per-dim is the source of truth (supports fine-grained review); bulk-approve is a UI shortcut (set all dims). No separate per-clause `tag_status` column (derived: all-approved => ready). "两种方式都支持" (both granularities).
**Alternatives**: Separate `tag_status` column (per-clause) - rejected (can't review per-dim). Separate `clause_tags` table - rejected (over-normalized; tags already JSONB).

### D5: Assembly gates only custom by review
**Choice**: `generate_contract_assembled` selects base (`tags.source=base`, all) + tagged (`tags.source=tagged ∧ tags.region=X`, all) + custom (`tags.source=custom ∧ tags match ∧ all dims approved`). base/tagged are the backbone (not review-gated); only custom is tag-filtered + review-gated.
**Rationale**: base/tagged come from 示范文本 (the骨架); custom (seeds/manual/auto-tagged) drives the tag-based selection and needs the quality gate. "直观custom".
**Alternatives**: Gate base/tagged too - rejected (backbone should always assemble; their auto-tags are informational).

### D6: Auto-tag at extraction (universal dims)
**Choice**: The extraction LLM prompt adds a `tags` field suggesting `stance/strength/risk/mandatory` for each clause. `source` is set from the doc's level (base/tagged). `region` from the inferred province. Auto-suggested universal tags enter `tag_review` as `pending`; type-specific dims stay manual (LLM doesn't know them).
**Rationale**: Tags scale with the corpus (not just manual). The LLM reliably judges 甲方/乙方 倾向, 风险, 强制性; type-specific dims need a human. "抽取的时候一起打标".
**Alternatives**: Auto-tag type-specific too - rejected (LLM unreliable on per-type dims). No auto-tag - rejected (tags don't scale).

### D7: Tag governance - reuse-or-create
**Choice**: `register_tag_dim(contract_type, name, category, values, free_form)` - if `(contract_type, name)` exists, merge values (don't duplicate); else create. The seeder (from manifests), extraction (auto-suggested dims), and manual entry all route through `register_tag_dim`. Manual entry of a new dim value on the dashboard also reuses the existing dim.
**Rationale**: Prevents dim proliferation (e.g. `non_compete_type` when `special_restriction_period` exists). "如果符合用现有的,没有的话就用新的".
**Alternatives**: Free creation (no dedup) - rejected (dims proliferate). Strict admin-only dim creation - rejected (too rigid for v1).

### D8: region from extraction province (direct, pending)
**Choice**: Extraction sets `tags.region` from the inferred province (already done) AND `tag_review.region=pending` (auto-set, needs review). The curated seed clauses' region tags are `approved` (curated).
**Rationale**: region is auto-derivable (extraction already infers province), so no LLM needed for it; but it's still auto-set -> pending review.
**Alternatives**: region approved-by-default (no review) - rejected (extraction's province inference can be wrong).

## Risks / Trade-offs

- **[Big migration]** Dropping `category`/`level` columns touches store/assemble/extract/seed/web/tests broadly (same scale as province->region). Mitigation: migrate data first (tags.source=category, tag_review approved for curated), then code, then drop columns; deploy; drop columns after.
- **[Per-type vocab complexity]** validate_tags now needs contract_type; TAG_VOCAB becomes per-type. Mitigation: `load_vocab_from_db()` builds a `{contract_type: {dim: values}}` map; validate_tags(tags, contract_type) looks up universal (NULL) + type.
- **[Auto-tag quality]** LLM-suggested stance/strength may be wrong. Mitigation: all auto-tags are `pending` (review-gated); assembly ignores pending. Curated seeds are approved.
- **[Review backlog]** Auto-tagging thousands of corpus clauses creates a pending backlog. Mitigation: bulk-approve UI; per-type review; the audit dashboard surfaces coverage.
- **[Assembly semantics shift]** base/tagged selected by `tags.source` instead of `category` column - functionally equivalent but every query changes. Mitigation: thorough tests.
