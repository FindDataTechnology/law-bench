## Context

The base layer is now clean: all 42 contract types have a single canonical 母版 (`source_doc_title='生成母版（{zh}）'`, 10 sections) seeded from `contracts.json`. The remaining blocker for usable tag-composed templates is the **assembly model**. `src/clauses/assemble.py:_assemble_body` groups clauses by section and concatenates every matching body (deduping only exact `body_hash`), so:

- Pulling `scenario=家具买卖` stacks a second full 当事人/标的/价款 on top of base (base + tagged both cover the same sections).
- `stance` adds nothing: all 187 custom clauses have empty `tag_review` -> `is_assembly_ready=False` -> none selected.
- The 1060 scenario-tagged clauses are whole 示范文本 re-imports (some clean at 1/section, e.g. 建材买卖; some with intra-doc piling, e.g. 家具买卖 3×标的/4×权利义务).

Data snapshot: tagged=5784 (only 1060 carry a `scenario`), custom=187 (0 assembly-ready). The 母版 in `contracts.json` carries per-type `slot_instructions` and defines the canonical slots. `is_assembly_ready` requires every tag dim to be `approved`.

## Goals / Non-Goals

**Goals:**
- Assembled contract is always **one clause per section** (plus extensions) - coherent by construction, regardless of data noise.
- `scenario` and `stance` meaningfully change the output: scenario overrides sections / extends new ones; stance overrides specific clauses.
- A single canonical slot vocabulary across all clauses; clauses normalized to it.
- A pre-release coherence gate so only valid templates are delivered.
- Reusable diff-based curation that converts whole-doc 示范文本 into true scenario overrides, piloted on `sale`.

**Non-Goals:**
- A rule/conditional engine (no "if amount > X then ..." logic).
- Auto-filling slots with real values - templates stay `{{slot}}`-fillable.
- Curating all 42 types in this change - only `sale` is piloted; the other 41 reuse the tooling as follow-on.
- Modifying the 母版 templates themselves.
- Real (human) legal review of custom clauses - we use the existing `bulk_review` gate; genuine review is follow-on.

## Decisions

### D1: Per-section override resolution, precedence `custom > tagged > base`
For each section, exactly one clause body is rendered, chosen as the highest-precedence clause that targets that section: `custom(stance)` > `tagged(scenario)` > `base(母版)`. Base is always the fallback.

- **Why**: guarantees no piling; matches template-inheritance reasoning (base form -> swap specialist sections -> adjust client-interest clauses).
- **Alt considered - "pick one whole template by scenario" (Model B)**: rejected because 示范文本 are noisy (intra-doc piling) and it cannot compose scenario + stance on the same section.
- **Alt considered - "clause marketplace with a scenario×stance resolution matrix" (Model C)**: deferred as over-engineered; a fixed precedence is a far simpler resolution rule and covers the cases we have.

### D2: Section extension for sections absent from base
A tagged/custom clause whose `section` is not in the 母版's section set is **extended** into the contract. Extended sections are inserted at a canonical rank: after their nearest canonical predecessor, and always before `附则`/`签署信息`.

- **Why**: scenarios like 农产品买卖 need a 检验/质量 section the generic 母版 lacks; override-only would silently drop it.
- **Alt**: refuse unknown sections - rejected, it blocks legitimate specialization.

### D3: Within-source variant tiebreak (stopgap until curation)
If a single source has multiple clauses for the same section (e.g. 家具买卖's 3 标的), the engine picks one by: `manual=true` first, then most `{{slot}}`s covered, then longest body, then lowest id. This is a documented stopgap; D6 curation is the real fix.

- **Why**: the engine must stay useful on today's noisy data instead of erroring until curation finishes.
- **Alt**: hard-error on multi-variant - rejected, it blocks all use.

### D4: Canonical slot vocabulary + write-time normalization
`src/contracts/slots.py` declares the canonical slot set per type (already implied by the 母版's `slot_instructions`). An alias map (`seller_name`->`party_a`, `buyer_name`->`party_b`, ...) is applied when clauses are written/upserted (`store._finalize`), so every clause body uses the canonical names.

- **Why**: cross-clause assembly consistency; prevents `{{seller_name}}` vs `{{party_a}}` mismatches seen in the sale 当事人 variants.
- **Alt**: normalize only at assembly time - rejected, it hides data debt and complicates the gate; normalizing on write makes the stored corpus the source of truth.

### D5: Coherence gate as a pre-render validation pass
Before rendering, validate: (a) every canonical section is present or explicitly extended; (b) no duplicate section in the resolved set; (c) every `{{slot}}` in the assembled body has a matching instruction; (d) resolved clauses don't carry contradictory stances (prevented by D1, but asserted). Failure surfaces as a tool error with a diagnostic.

- **Why**: "usable template" requires a quality bar; the gate makes incoherence a hard failure, not silent.
- **Alt**: soft warn-and-deliver - rejected for the strict path; the proposal specifies a tool error.

### D6: Scenario override curation via diff against 母版
For a corpus 示范文本 doc: split into sections; for each section, compute similarity to the 母版's same section (token Jaccard / rapidfuzz ratio); keep only sections below a similarity threshold (genuinely different) as `tagged` overrides; near-duplicates are discarded; multi-variant sections collapse to the best one. Output replaces the whole-doc re-import for that scenario.

- **Why**: override semantics (D1) need tagged clauses to be *differences*, not a second full contract. Diff-based extraction is automatable and turns the 1060 re-imports into a small set of true overrides.
- **Alt**: manual curation - too slow for 42×N; semi-automated diff + human spot-check scales.

### D7: Stance effectiveness via existing `tag_review` / `bulk_review`
Custom clauses are routed through `bulk_review(id, "approved")` so `is_assembly_ready` passes and `stance` selects them. Pilot: bulk-approve `sale`'s 5 custom clauses.

- **Why**: the gate already exists and is the designed path; no new mechanism needed.
- **Risk acknowledged**: bulk-approving without human review lets unvetted clauses in - acceptable for the pilot, flagged in output, real review is follow-on.

## Risks / Trade-offs

- **[Override drops complementary sub-clauses]** If a section legitimately has complementary parts (甲方权利 + 乙方权利 as separate clauses), override keeps one. -> *Mitigation*: the 母版 keeps them in one body; curation merges split sub-clauses back to one body per section. Clause granularity = one body per section.
- **[Tiebreak picks a worse variant]** Until D6 curation lands, the D3 heuristic may choose a poorer clause. -> *Mitigation*: pilot curation on `sale` first; flag heuristic-sourced contracts in the gate diagnostic.
- **[Bulk-approve injects unvetted stance clauses]** -> *Mitigation*: pilot-only, mark `tag_review=approved` without real review, surface in diagnostics; genuine review is a follow-on change.
- **[Extended sections land in odd positions]** -> *Mitigation*: canonical rank with extension slots before `附则`/`签署信息`; covered by a gate check.
- **[Diff threshold tuning]** The similarity cutoff for "genuinely different" needs empirical tuning per type. -> *Mitigation*: tune on `sale` first; expose threshold as a parameter.
- **[Slot alias map incomplete]** Unknown slot aliases slip through un-normalized. -> *Mitigation*: a gate check fails on any un-instructed slot, surfacing missing aliases for the map.

## Migration Plan

1. **Engine + gate + slot vocab (code-only)** - ships first. Immediately improves every type: override resolution means even noisy tagged data no longer piles (one clause per section via D3 tiebreak). Revert restores concat behavior.
2. **`sale` scenario curation pilot** - run D6 diff curation on `sale`'s 示范文本, replacing whole-doc re-imports with diff-based overrides. Rollback snapshot retained (existing pattern from the base-pollution fix).
3. **`sale` stance enablement** - `bulk_review` approve `sale`'s 5 custom clauses.
4. **Other 41 types** - follow-on, reusing D6 tooling (out of scope for this change).

No external API consumers lose value: the assembled output shape (`{docx_path, pdf_path, slots, instructions, law_refs}`) is unchanged; only body semantics shift from concat to override, and the current concat output is already broken.

## Open Questions

- Exact diff similarity threshold (needs tuning on `sale`).
- Canonical insertion rank for extended sections - fixed (before `附则`) or type-specific?
- Should the coherence gate be strict-error (proposal says yes) or warn+deliver for non-pilot types? Confirm strict for now.
- Completeness of the slot alias map - requires a one-time scan of all clause bodies for slot variants.

## Follow-ons (out of scope for this change)

- **Human spot-check** of the curated `sale` scenario overrides (task 4.5) - the diff curation + tiebreak are automated; a legal review pass confirms quality.
- **Transparency marker** for pilot-approved custom clauses (task 5.2) - `sale`'s 5 custom clauses were `bulk_review`-approved without human review; a formal "auto-approved" field/marker is desirable.
- **Real `tag_review`** of custom clauses across all types (not just `sale` pilot).
- **Curate the remaining 41 contract types** - reuse `scripts/curate_sale_overrides.py` (diff + collapse) and `scripts/retag_batch_types.py` (base-pollution -> tagged+scenario). Each type needs the same base-clean + scenario-curation + stance-enablement pass.
- **Seed the `capital_increase` 母版** (currently `base=0` -> empty assembled contract).
- **Slot ontology long tail** - ~5184 single-occurrence slots are uncovered; an uninstructed one fails the gate as surfaced debt. Extend the registry or LLM-generate instructions for medium-frequency concepts.
- **law_refs dedup** - "中华人民共和国民法典" vs "民法典" appear as separate refs (exact-name dedup misses the synonym); consider normalizing law-ref names.
