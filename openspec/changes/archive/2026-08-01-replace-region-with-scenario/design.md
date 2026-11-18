## Context

`unify-clause-tags` (archived 2026-07-31) unified clause classification into `tags` and kept `region` (province) as the one free-form, provenance-derived dimension - explicitly deferring a `业务场景` (B2B/B2C/行业) category. Region carries a rules subsystem: extraction auto-sets `tags.region` from the inferred province (entering `tag_review` as `pending`), `generate_contract_assembled(province=)` selects `source=tagged` clauses where `tags.region == province`, output files are named `<type>__<province>`, `store._row` strips `region` for national clauses, `counts_by_type` reports `provinces`, and the web detail view has a region filter dropdown. The MCP tool `generate_contract_from_tags` surfaces this via `tags={"region":...}` / `tags={"province":...}`.

A corpus analysis (proposal) of 587 extracted docs across 33 provinces found:
- Clauses cluster by **section**, not province (same-province/diff-section similarity 0.009 vs diff-province/same-section 0.069).
- The `当事人` section across provinces shows the real variation is transaction **sub-type**: `sale` = 混凝土建材 / 消费零售 / 学校采购 / 展销会; `service` = 驾校 / 养老 / 学校 / 消费. Province is provenance and hides this.
- Region values are inconsistent (`京` vs `北京`).
- `real_estate_lease` is the partial exception with more genuine regional variation, but province is still not a clean axis.

User direction (2026-08-01): province `region` is not important; replace it with a new dimension. Decision: a per-type `scenario` (业务场景) controlled vocabulary, auto-tagged at extraction (LLM + review), with a one-time retag of the existing corpus.

## Goals / Non-Goals

**Goals:**
- Drop province `region` (dimension + its 6-file rules subsystem + the `京`/`北京` mess).
- Introduce a per-type `scenario` (业务场景) controlled vocabulary, seeded from the corpus analysis.
- Auto-tag `scenario` at extraction (LLM-suggested, `pending` review) - scenario is body-judgeable, unlike province.
- Assembly/MCP/web select by `scenario` instead of province.
- Retag the existing extracted corpus (~5000 clauses) with `scenario` via a one-time LLM pass.

**Non-Goals:**
- Touching the 131 type-specific legal dims or the universal `stance`/`strength`/`risk`/`mandatory` dims.
- Collapsing `source` ∈ {base, tagged, custom} (the backbone stays; `tagged` is now selected by scenario).
- Re-introducing province as a display facet (can be a follow-up if ever needed).
- Deduping near-duplicate cross-region clauses (scenario subsumes the useful distinction; near-dups become same-scenario and are handled by existing body_hash dedup in assembly).
- Tag value normalization beyond region (moot once region is dropped).

## Decisions

### D1: `scenario` is a per-type controlled vocabulary (category 业务场景)
**Choice**: One `scenario` dim per type: `tag_dims(contract_type=<key>, name='scenario', category='业务场景', values=[...])`. Each type's values come from analyzing its extracted corpus (primarily the `当事人`/`标的` sections). Types with little sub-type variation get a minimal vocab (possibly a single value + `其他`).
**Rationale**: The analysis shows sub-types differ per type (`sale` vs `service` have disjoint scenario sets). Per-type matches the existing type-specific dim pattern and the user's chosen granularity.
**Alternatives**: (a) Universal scenario vocab (B2B/B2C/机构/消费) - rejected (loses precision: can't distinguish 驾校 from 养老 within `service`). (b) Free-form scenario - rejected (recreates the `京`/`北京` mess for scenario). (c) Keep `region` alongside - rejected (dual axes, messy values, user wants region gone).

### D2: Auto-tag `scenario` at extraction (LLM, pending review)
**Choice**: The extraction LLM prompt adds a `scenario` suggestion per clause (judged from body/parties/标的), entering `tag_review` as `pending` - identical to how `stance`/`strength` are auto-tagged. `source` derivation from `level` is unchanged.
**Rationale**: Scenario is body-judgeable (we can read 驾校/养老/混凝土 from the text), unlike province (provenance). The pending-review gate handles LLM mislabels.
**Alternatives**: (a) Manual curation per scenario - rejected (slow; doesn't cover the extracted corpus). (b) Forward-only tagging - rejected (assembly-by-scenario stays empty until new extractions).

### D3: `scenario` replaces `region` in assembly
**Choice**: `generate_contract_assembled` drops `province`; gains `scenario`. It selects `source=tagged` clauses where `tags.scenario == scenario` (+ base + custom by stance/ids). Output naming: `<contract_type>__<scenario>.<ext>` (no `__province`). `tagged` clauses are now grouped by scenario, not province.
**Rationale**: Direct replacement; preserves the base+tagged+custom assembly model with scenario as the tagged-selection axis.
**Alternatives**: (a) Drop tagged selection entirely - rejected (loses the sub-type selection the user wants). (b) Select tagged by both scenario AND province - rejected (province is gone).

### D4: Retag the existing corpus via a one-time LLM pass
**Choice**: A migration job runs the extraction LLM (or a lighter classify-only prompt) over existing clauses to assign `tags.scenario` (pending review), then drops `tags.region` and `tag_review.region`. Bulk-approve UI handles the backlog per type.
**Rationale**: User chose LLM auto-tag + review; the existing corpus must get `scenario` for assembly-by-scenario to be non-empty.
**Alternatives**: (a) Re-extract all 587 docs with the new prompt - rejected (expensive; loses any manual curation). (b) Hand-tag - rejected (5000 clauses). A classify-only pass over stored bodies is cheaper than full re-extraction.

### D5: Drop `region` entirely (dimension + rules + values)
**Choice**: Remove `region` from `FREE_FORM_TAGS`, the `tag_dims` seed, `_row` region-strip, `counts_by_type` `provinces`, the web region filter, and the MCP `region`/`province` key handling. Existing `tags.region` values are deleted in migration (they are provenance, not worth preserving as display).
**Rationale**: Keeping region as display contradicts the user's "region is not important" and leaves a second axis. Dropping it also kills the `京`/`北京` normalization problem.
**Alternatives**: (a) Keep region as display-only metadata - rejected (user said region is not important; dual axes confuse assembly). (b) Normalize region values but keep the dim - rejected (preserves the wrong axis).

### D6: Scenario vocab seeding + governance
**Choice**: Seed each type's `scenario` values from the corpus analysis (enumerate sub-types per type from `当事人`/`标的` sections). Add to the per-type manifests' `tags[]` so `seed_tag_dims` loads them. New scenario values route through `register_tag_dim` (reuse-or-create) so the vocab stays governed.
**Rationale**: Reuses the existing manifest + `seed_tag_dims` + governance machinery; no new infra.
**Alternatives**: A separate scenario-only seed file - rejected (fragments the vocab source).

## Risks / Trade-offs

- **[Scenario vocab incomplete]** A type's seeded scenario values may miss a sub-type present in the corpus. -> Mitigation: `validate_tags` drops unknown `scenario` values silently (normalize_tags); the retag LLM can flag unrecognized scenarios for vocab extension via `register_tag_dim`; `其他` fallback per type.
- **[Retag backlog]** ~5000 clauses enter `tag_review` as pending. -> Mitigation: bulk-approve per type; classify-only prompt is cheap; assembly ignores pending (only approved scenario clauses assemble).
- **[LLM mislabels]** Scenario auto-tags can be wrong. -> Mitigation: pending review gate; assembly uses only approved; curated seeds approved by default.
- **[BREAKING]** `generate_contract_assembled(province=...)` and `generate_contract_from_tags(tags={"region":...})` change to `scenario`. -> Mitigation: clean error on `province=`; documented `scenario` key; changelog note.
- **[real_estate_lease]** It had more genuine regional variation; dropping province loses that granularity. -> Mitigation: scenario captures the sub-type distinction (住宅/商业/办公 lease differ by scenario, not province); province-level variation was minor vs sub-type.
- **[Cost]** One LLM pass over ~5000 clauses. -> Mitigation: classify-only prompt (no re-extraction); batched; one-time.

## Migration Plan

1. **Seed vocab**: enumerate per-type `scenario` values from the corpus analysis; add to manifests; `seed_tag_dims`.
2. **Code**: implement scenario auto-tag (extract), scenario assembly (assemble), drop region (store/tags/web/MCP).
3. **Retag job**: classify-only LLM pass over existing clauses -> `tags.scenario` (pending); `UPDATE clauses SET tags = tags - 'region', tag_review = tag_review - 'region'`.
4. **Deploy**: ship code + run retag/migration. Rollback: revert code; re-adding `region` is a separate change (region values are dropped, but docs can be re-extracted).
5. **Verify**: tests pass; assembly-by-scenario works; MCP `tags={"scenario":...}` filters; region is gone from UI/assembly/MCP.

## Open Questions

- Should `scenario` be single-value or multi-value per clause (a clause could plausibly span scenarios)? **Lean**: single-value (matches the existing one-dim-one-value tag model); revisit if retag shows frequent ambiguity.
- For types with minimal sub-type variation (e.g. `gift`, `loan` - 1 region each), is a single-value `scenario` vocab meaningful, or should `scenario` be optional per type? **Lean**: seed a minimal vocab (`其他` + any obvious split) so the dimension is uniform; assembly with no scenario just returns base+custom.
- Enumerate the exact per-type scenario vocabs during task 1 (corpus analysis) - the examples in the proposal (sale/service) are illustrative.
