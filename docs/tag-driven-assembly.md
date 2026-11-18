# Tag-Driven Contract Assembly

How a `contract_type` + tags (`scenario`, `stance`) become one coherent, fillable contract.

## Model: per-section override (not concatenation)

```
resolved section = custom(stance)  ─┐
                > tagged(scenario) ─┤  precedence: first match wins
                > base(母版)       ─┘  base is always the fallback
```

- Each section renders **exactly one** clause body (no piling).
- A tagged/custom clause whose `section` is absent from the 母版 is **extended** into the contract, inserted before `附则`.
- Within one source, if multiple clauses target the same section, one is picked by tiebreak: `manual=true` > most `{{slot}}`s > longest body > lowest `id`. Sections resolved this way are flagged in `result["diagnostics"]["heuristic_sections"]` (clean data -> empty list).
- Before rendering, a **coherence gate** (`src/clauses/coherence.py`) validates: every 母版 section present, no duplicate section, every `{{slot}}` has an instruction. Failure raises `CoherenceError` (surfaces as an MCP tool error; no file written).

Entry point: `src.clauses.assemble.generate_contract_assembled(contract_type, scenario=..., stance=..., format=...)`. Exposed as the `contract_generate` MCP tool.

## Slots: ontology + normalization

- Canonical core: the 12 `REQUIRED_SLOTS` (`party_a`, `party_b`, `subject`, `amount`, `term_start`, `term_end`, `party_a_duty`, `party_b_duty`, `penalty`, `jurisdiction`, `sign_date`, `sign_location`).
- Extended concepts live in `src/contracts/slot_ontology.py` (`address`, `phone`, `agent`, `legal_rep`, `bank`, `account`, `delivery_date`, ...) with alias + role-prefix maps (e.g. `seller_address` -> `party_a_address` for `sale`; `lessor_address` -> `party_a_address` for `lease`).
- Clause bodies + `slot_instructions` are normalized to canonical slot names at write time (`store._row`); `body_hash` is re-derived from the normalized body. Unknown single-occurrence slots are left as-is; if one lacks an instruction the coherence gate flags it as data debt.
- Instructions: 12 canonical defaults ∪ clause-declared ∪ ontology fallback, so any known slot is instructed.

## Data layers

| layer | `tags.source` | role | filtered by |
|---|---|---|---|
| base | `base` | 母版 backbone (10 canonical sections) | always included |
| tagged | `tagged` | scenario-specific **overrides/extensions** | `tags.scenario` |
| custom | `custom` | stance-specific overrides | `tags.stance` + `is_assembly_ready` (every tag dim `approved` in `tag_review`) |

## Curating a contract type (follow-on playbook)

`sale` is the pilot. To curate another type (e.g. `lease`):

1. **Clean base** — ensure exactly one 母版 base clause per canonical section (`source_doc_title='生成母版（{zh}）'`, `manual=true`). If base is polluted by 示范文本 re-imports, re-tag them to `source=tagged` + `scenario=<derived>` (`scripts/retag_batch_types.py` is the pattern; see `sale-base-pollution-fix` memory).
2. **Curate tagged** — run `scripts/curate_sale_overrides.py` adapted to the type: it diffs each tagged clause against the 母版 same section (`difflib` ratio), discards near-duplicates (base covers them), collapses multi-variant sections to one per `(scenario, section)`. Threshold is tunable (`--threshold`, default 0.7).
3. **Enable stance** — `bulk_review(cid, "approved")` each custom clause so `is_assembly_ready` passes. Add a `tag_review._note` marker if approving without human review.
4. **Verify** — `generate_contract_assembled(type, scenario=X, stance=Y)` should produce one-clause-per-section, empty `heuristic_sections`, and pass the gate.

Rollback snapshots are written by each script (`output/_retag_rollback_*.json`, `output/_sale_curate_rollback.json`, `output/_slotnorm_rollback.json`).

## Known gaps / follow-ons

- `capital_increase` has `base=0` (no 母版 seed) -> empty assembled contract.
- 41 types beyond `sale` need the curation pass above.
- Custom clauses across types need real (human) `tag_review`, not just pilot auto-approval.
- Slot ontology long tail (~5184 single-occurrence slots) is uncovered.
- `law_refs` dedup is exact-name only ("中华人民共和国民法典" vs "民法典" are separate).
