## Why

The `region` (province) tag dimension is the wrong axis. An analysis of 587 extracted 示范文本 docs (33 provinces; `sale` 22 regions / 1336 clauses, `service` 19 regions, `real_estate_lease` 19) shows clauses cluster by **section**, not province: same-province/different-section similarity ≈ 0.009 vs different-province/same-section ≈ 0.069 (7× higher). The `当事人` section across provinces reveals the real variation is transaction **sub-type (业务场景)**, not geography: `sale` collapses 混凝土建材 / 消费零售 / 学校采购 / 展销会三方; `service` collapses 驾校培训 / 养老机构 / 学校 / 消费服务. Province is pure provenance - it violates the "tags are curatorial, not derived from the clause body" principle from `unify-clause-tags` and actively hides the real sub-type structure. It is also exactly the deferred `业务场景` dimension (B2B/B2C/行业) that `unify-clause-tags` explicitly postponed, and its free-form values are messy (`京` vs `北京`). Replace province `region` with a per-type `scenario` (业务场景) controlled vocabulary, auto-tagged at extraction.

## What Changes

- **DROP `region` (province)** as a tag dimension. The free-form province string and its rules subsystem (auto-tag -> pending review -> assembly-by-province -> `__province` file naming -> region-strip for national -> region filter UI) are removed.
- **ADD `scenario` (业务场景)** as a per-type controlled-vocabulary dimension (`tag_dims(contract_type=<key>, name='scenario', category='业务场景', values=[...])`), seeded per type from the corpus analysis. Example vocabs: `sale` -> {建材工业品, 消费品零售, 机构采购, 展销会, 农产品, 二手}; `service` -> {驾校培训, 养老服务, 教育培训, 消费服务, ...}. Types with little sub-type variation get a minimal vocab.
- **Auto-tag `scenario` at extraction.** The extraction LLM suggests `scenario` per clause (judgeable from the body/parties - unlike province, which is provenance); enters `tag_review` as `pending` (same pattern as `stance`/`strength`). `source` derivation (`base`/`tagged` from `level`) is unchanged.
- **Assembly by scenario.** `generate_contract_assembled` drops `province`; gains `scenario`. It selects `source=tagged` clauses where `tags.scenario == scenario` (replacing the `tags.region == province` filter). Output file naming becomes `<contract_type>__<scenario>.<ext>`.
- **BREAKING** - `generate_contract_from_tags` (MCP): `tags` recognizes `scenario`; `region`/`province` keys are no longer recognized.
- **Retag the extracted corpus.** One-time LLM pass over existing clauses assigns `scenario` (pending review); `tags.region` is dropped.
- **Web:** the region filter dropdown becomes a `scenario` filter; clause cards display `scenario` instead of `region`.
- (Dropping `region` also dissolves the `京`/`北京` value-normalization problem.)

## Capabilities

### New Capabilities
(none - `scenario` is a new dimension within the existing clause-tag model, governed through the modified assembly behavior)

### Modified Capabilities
- `law-bench-mcp`: `generate_contract_from_tags` recognizes `scenario` in `tags` (not `region`/`province`) and delegates to `generate_contract_assembled(scenario=...)` so tagged-clause selection is filtered by scenario.

## Impact

- **Modified code**: `src/clauses/extract.py` (auto-tag `scenario`, stop setting `tags.region`); `src/clauses/assemble.py` (drop `province`, add `scenario` param + `tags.scenario` selection + `<type>__<scenario>` naming); `src/clauses/store.py` (drop region-strip + `provinces` breakdown; add `scenario` facet); `src/clauses/tags.py` (drop `region` from `FREE_FORM_TAGS`; `scenario` is a per-type controlled dim); `src/clauses/seed_manifest.py` (seed per-type `scenario` dims); `src/web/routes/clauses.py` + 4 templates (scenario filter/display); `fd-coding-law-bench-mcp/.../tools/generate.py` (`tags` -> `scenario`).
- **New data**: per-type `scenario` vocab seeded from the corpus analysis (manifest `tags[]` entries or a dedicated scenario seed).
- **Data migration**: drop `tags.region`; assign `tags.scenario` via a one-time LLM retag (pending review); drop `tag_review.region`.
- **BREAKING API**: `generate_contract_assembled(province=...)` -> `(scenario=...)`; `generate_contract_from_tags(tags={"region":...})` -> `tags={"scenario":...}`.
- **Cost**: one LLM pass over ~5000 extracted clauses for retagging (review-gated, bulk-approvable).
- **Dependencies**: none new.
- **Out of scope**: the 131 type-specific legal dims (kept); `source` ∈ {base, tagged, custom} backbone (kept); `stance`/`strength`/`risk`/`mandatory` universal dims (kept); re-introducing province (a future change can re-add it as a display facet if ever needed).
