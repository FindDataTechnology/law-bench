## Why

Tag-driven contract assembly currently **concatenates every matching clause per section** (`_assemble_body` joins all base+tagged+custom bodies, deduping only exact `body_hash` duplicates). This means any non-empty `scenario` or `stance` tag re-introduces the "Frankenstein" problem we just fixed at the base layer: pulling `scenario=家具买卖` stacks a second 当事人/标的/价款 on top of the 母版, and `stance` adds nothing because all 187 custom clauses fail the `is_assembly_ready` gate. The base layer is now clean across 42 types, but the **assembly model itself** is the bottleneck preventing tags from composing usable templates. We need composition semantics that are coherent by construction.

## What Changes

- **Override + extend assembly engine.** Each section renders exactly ONE clause body, resolved by precedence `custom(stance) > tagged(scenario) > base(母版)`; base is the fallback for any section an override does not touch. Tagged/custom clauses whose `section` is absent from base are **extended** into the contract at a canonical position. **BREAKING**: assembled output no longer concatenates multiple clauses within a section (the contract is always one-clause-per-section plus extensions).
- **Canonical slot vocabulary.** A single normalized slot set (e.g. `party_a`, `party_b`, `subject`, `amount`, `term_start`, `term_end`, `party_a_duty`, `party_b_duty`, `penalty`, `jurisdiction`, `sign_location`, `sign_date`) governs all clauses; clauses are migrated/normalized to it so cross-clause assembly stays slot-consistent (no `{{seller_name}}` vs `{{party_a}}` mismatches).
- **Coherence gate.** A pre-release validation pass rejects/flags contracts with duplicate sections, un-instructed slots, or missing canonical sections, so only coherent templates are delivered.
- **Scenario override curation tooling.** A diff-based process that, for a given 示范文本 corpus doc, retains only the sections that genuinely differ from the 母版 (true overrides), cleans to one clause per section per scenario, and replaces the current "whole-doc re-import as tagged" data. Piloted on `sale`, reusable for the other 41 types.
- **Stance effectiveness path.** Custom clauses are routed through the existing `tag_review` / `bulk_review` gate so `stance` actually selects clauses into the assembled contract.

## Capabilities

### New Capabilities
- `contract-assembly`: Override-and-extend clause composition engine — per-section precedence resolution (`custom > tagged > base`), base fallback, section extension, canonical slot vocabulary, and the pre-release coherence gate. Covers the behavior that turns a `contract_type` + tags into one coherent, fillable contract body.

### Modified Capabilities
- `law-bench-mcp`: The `Generate Contract from Tags` requirement changes — `contract_generate` with `stance`/`scenario` now produces an override-resolved, one-clause-per-section contract (no concatenation piling), and a coherence failure surfaces to the client as a tool error.

## Impact

- **Code**: `src/clauses/assemble.py` (`_select_clauses` precedence, `_assemble_body` override/extend rewrite), `src/contracts/slots.py` (canonical vocab + normalization helper), new coherence-gate module, `src/clauses/store.py` (slot-normalization on write/upsert). `fd-coding-law-bench-mcp` tool behavior.
- **Data**: re-curation of `sale` tagged clauses into diff-based overrides (pilot); bulk `tag_review` approval of `sale` custom clauses. Other 41 types are follow-on (same tooling).
- **APIs/contracts**: assembled-contract output shape is unchanged (`{docx_path, pdf_path, slots, instructions, law_refs}`) but body content semantics change (override, not concat). Rollback snapshots from the prior base-pollution fix are unaffected.
- **Tests**: `tests/test_assemble*`, `tests/test_generate_tool.py` updated for override semantics + coherence gate.
