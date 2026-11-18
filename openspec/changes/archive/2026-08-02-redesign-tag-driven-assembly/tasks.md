## 1. Override Resolution Engine

- [x] 1.1 Refactor `_select_clauses` (`src/clauses/assemble.py`) to return candidates grouped by `(section, source)` without concatenation semantics - base, tagged(scenario), assembly-ready custom(stance) collected separately
- [x] 1.2 Implement per-section override resolution with precedence `custom > tagged > base` and base fallback, yielding exactly one clause body per section
- [x] 1.3 Implement section extension: clauses whose `section` is absent from the 母版 canonical set are inserted before `附则`/`签署信息` at a canonical rank
- [x] 1.4 Implement within-source variant tiebreak (`manual=true` -> most `{{slot}}`s -> longest body -> lowest `id`) and record heuristic-sourced sections in a diagnostic structure
- [x] 1.5 Rewrite `_assemble_body` to emit one body per resolved section (remove the multi-body concatenation + `body_hash` join)
- [x] 1.6 Expose the heuristic-sourced diagnostic on the assembled result so callers can see which sections used a tiebreak

## 2. Canonical Slot Vocabulary

- [x] 2.1 Declare the canonical slot vocabulary per `contract_type` in `src/contracts/slots.py`, derived from each 母版's `slot_instructions`
- [x] 2.2 One-time scan of all clause bodies to enumerate non-canonical slot tokens (e.g. `seller_name`, `buyer_name`, `receiver`) and build the alias map
- [x] 2.3 Declare the slot alias map (`seller_name` -> `party_a`, `buyer_name` -> `party_b`, ...) in `src/contracts/slots.py`
- [x] 2.4 Add slot normalization to `src/clauses/store.py:_finalize` so clause bodies are rewritten to canonical slots on write/upsert
- [x] 2.5 Backfill: normalize existing clause bodies in the DB to canonical slots (one migration run per type)

## 3. Coherence Gate

- [x] 3.1 Add a coherence validation module (`src/clauses/coherence.py`) that takes the resolved section set + assembled body + instructions
- [x] 3.2 Check: every canonical 母版 section is present or explicitly extended
- [x] 3.3 Check: no duplicate section in the resolved set
- [x] 3.4 Check: every `{{slot}}` in the assembled body has a matching entry in `instructions`
- [x] 3.5 Wire the gate into `generate_contract_assembled` before rendering; on failure abort (no file written) and return a diagnostic naming the failing check
- [x] 3.6 Surface the coherence diagnostic through `contract_generate` as a tool error (per `law-bench-mcp` MODIFIED spec)

## 4. sale Scenario Curation Pilot

- [x] 4.1 Build a diff-curation script (`src/clauses/curate_overrides.py`): split a corpus 示范文本 by section, compute similarity vs the 母版's same section (rapidfuzz ratio / token Jaccard), expose a tunable `--threshold`
- [x] 4.2 Run curation on `sale`'s 示范文本: keep only sections below threshold as `tagged` overrides, discard near-duplicates, collapse multi-variant sections to one clause per section per scenario
- [x] 4.3 Replace `sale`'s whole-doc re-import tagged clauses with the curated diff-based overrides (rollback snapshot retained)
- [x] 4.4 Verify `contract_generate(sale, scenario=家具买卖)` produces a one-clause-per-section contract that passes the coherence gate
- [ ] 4.5 Human spot-check of the curated `sale` scenario overrides

## 5. sale Stance Enablement

- [x] 5.1 `bulk_review` approve `sale`'s 5 custom clauses (`tag_review` all dims -> `approved`) so `is_assembly_ready` passes
- [x] 5.2 Mark the pilot approval as approved-without-human-review in a diagnostic/field for transparency
- [x] 5.3 Verify `contract_generate(sale, stance=balanced)` includes the balanced custom clause overriding its section; verify `pro_a`/`pro_b` produce differing bodies

## 6. Tests & Validation

- [x] 6.1 Update `tests/test_assemble*` for override semantics: override-replaces-base, custom-overrides-tagged, base-fallback, section-extension, within-source-tiebreak
- [x] 6.2 Update `tests/test_generate_tool.py`: no-concatenation-within-section, coherence-failure-surfaces-error, scenario+stance composition
- [x] 6.3 Add coherence-gate unit tests (missing section, duplicate section, un-instructed slot, happy path)
- [x] 6.4 Add slot-normalization unit tests (alias rewrite on write, assembled body uses only canonical slots)
- [x] 6.5 End-to-end: generate all 42 types with no tags -> each is one-clause-per-section and passes the coherence gate
- [x] 6.6 MCP smoke test: `contract_generate(sale, scenario=建材工业品, stance=balanced, format=both)` via the law-bench MCP server returns a coherent deliverable

## 7. Rollout & Docs

- [x] 7.1 Move the curation/retag scripts from `/tmp` into the repo (`src/clauses/curate_overrides.py`, reuse for other types)
- [x] 7.2 Document the override model + diff-curation process so the other 41 types can be curated as follow-on
- [x] 7.3 Record known follow-ons (out of scope): real `tag_review` of custom clauses; curating the remaining 41 types; seeding the `capital_increase` 母版 (currently base=0)
