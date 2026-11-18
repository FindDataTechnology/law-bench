## Context

Built atop `add-clause-knowledge-base` (complete) and `add-clause-admin-dashboard` (complete):

- **Table** `clauses(..., manual boolean)` with additive columns via `_ADDITIVE_COLUMNS` in `src/eval/store.py`; `manual=true` preserves dashboard clauses across re-extraction. Custom clauses (source_path null) are plain inserts - there is **no** dedup index on `(section, body_hash)` for them (the partial unique index is `WHERE source_path IS NOT NULL`).
- **Store** (`src/clauses/store.py`): `create_clause`/`update_clause` re-derive `body_hash`/`slot_instructions`/`law_refs` from the body and set `manual=true`; `list_clauses`/`search_clauses` filter by `contract_type`/`category`/`province`/free-text `q`.
- **Assembly** (`src/clauses/assemble.py`): `_select_clauses` picks base (type) + tagged (type+province) + custom (by id), ordered by `section_rank`.
- **Extraction** (`src/clauses/extract.py`): `_law_refs_from_body` and `_normalize_slot_instructions` are the *only* body-derived fields. Tags are deliberately kept out of this set.

**Pivot (2026-07-30).** An earlier draft proposed a universal 4-tag schema + a pool of 10 cross-cutting seed families applied broadly. On review this was "大而全" - it would pad every contract type with generic clauses and miss type-specific signals. The user redirected to **per-type specific** tags + clauses, each type run through an analyze -> evaluate -> decide flow with honest skip. A pilot on `employment` (Kimi consultation) validated the flow: 2 type-specific tag dims (特殊约束期属性, 工时制度类型), 4 verified-法条 clauses (§22 / §23-24 / §39+劳部发503号 / §4), 4 honest skips (试用期 / 报酬 / 社保 / 劳动保护 - 法定强制/必备条款, already in base). Two AIs consulted (Claude + Kimi); 豆包 was unreachable via the `.env` relay (no doubao model; no Ark key; litellm proxy down) - Kimi adopted as the consultation model. See the `llm-relay-and-models` memory.

## Goals / Non-Goals

**Goals:**
- Per-contract-type **specific** tags and clauses, discovered by analysis - not a universal pool.
- A **growable** controlled vocabulary: a minimal universal starter set + type-specific dimensions added on real need.
- **Honest skip** as a first-class output: a type that yields nothing new is recorded as such, with reasons - never padded.
- **Real 《法条》**: every seed clause cites a real, current statute with article numbers (or is marked 待核); never fabricated.
- A reusable per-type manifest format so the analyze/evaluate/decide artifacts are reviewable before loading.

**Non-Goals:**
- A universal seed pool applied across all types (rejected).
- Predefining all tag dimensions up front (the vocabulary grows from real per-type need).
- Free-form / user-defined tags (controlled vocab, validated).
- An LLM auto-tagger (human/curator in the loop for v1).
- Backfilling tags onto existing extracted clauses (they stay untagged until curated).
- The `compliance`/`negotiability` dimensions (follow-up change).

## Decisions

### D1: Growable vocabulary, not a fixed universal tag set
**Choice**: `TAG_VOCAB` starts with the minimal universal starter set `stance/strength/risk/mandatory` and **grows** as per-type analysis proposes type-specific dimensions (e.g. `special_restriction_period`, `working_hours_system` for `employment`; `vam_mechanism` for `vam_agreement`). `register_tag_dim(name, values)` adds a dimension after review; `validate_tags` enforces the current vocab.
**Rationale**: The whole point of the pivot is that a 大而全 universal set either misses type signals or pads types. A growable vocab keeps facets meaningful while letting each type introduce only what it genuinely needs. The starter 4 are kept because they are truly universal (every contract has 甲方/乙方, risk, strength, mandatory/default nature) - they are a floor, not a universal taxonomy.
**Alternatives**: A fixed 4-dim schema for all types - rejected (misses type-specific signals like 违约金合法性闸门). Fully free-form tags - rejected (Non-Goal; fragments facets).

### D2: Tags are NOT re-derived from the body
**Choice**: `create_clause`/`update_clause` persist `tags` as given (validated); editing `body` does **not** touch `tags`. The opposite of `slot_instructions`/`law_refs`, which ARE re-derived.
**Rationale**: Stance/strength/risk/mandatory + type-specific dims are curatorial judgments with no deterministic mapping from clause prose. Re-deriving would silently null them on every body edit, destroying curation.
**Alternatives**: Re-derive from body - rejected (no signal; destroys curation). LLM re-suggest on each edit - rejected (non-deterministic; out of scope).

### D3: Extraction does not set tags
**Choice**: `extract._post_process` does not populate `tags`; extracted clauses are stored with `tags={}` and curated later.
**Rationale**: The extractor already struggles to infer province/level reliably; type-specific dims are softer still. Forcing a guess would seed wrong tags that look authoritative. Untagged-but-honest is preferable.
**Alternatives**: Have the extraction LLM also emit tags - rejected (reliability; prompt bloat).

### D4: Assembly `stance` filter applies only to custom clauses
**Choice**: `generate_contract_assembled(..., stance=None)` filters the *custom* clause selection to `tags->>'stance' = stance`; base and tagged clauses are unaffected.
**Rationale**: Base/tagged clauses are neutral 示范文本; the stance axis lives in the curated custom layer. Filtering the backbone would drop mandatory sections.
**Alternatives**: Filter all categories by stance - rejected (most base/tagged are untagged; would empty the contract).

### D5: Per-type manifest `data/clause_seeds/<type>.yaml` + idempotent loader (replaces the universal seed pool)
**Choice**: Each contract type has a YAML manifest `{tags: [...], clauses: [...], skipped: [...]}` where each clause also carries `slot_instructions: [{name, label, description, example, required}]` covering every `{{slot}}` in its `body`. `scripts/seed_stance_clauses.py [--type <key>]` reads the manifest(s), first deletes existing seed clauses for the type (`source_doc_title='seed:<contract_type>'`), then inserts via `create_clause` (`manual=true`), passing `tags` and `slot_instructions` through (preserved by `_finalize`/`_normalize_slot_instructions`). Delete-then-insert makes it idempotent (custom clauses have no `(section, body_hash)` dedup index).
**Rationale**: Separating the analyze/evaluate/decide artifacts (the manifest) from loading makes the curated content reviewable and reproducible. The marker-based delete handles the custom-clause dedup gap cleanly.
**Alternatives**: A single `seed_stance_clauses.json` for all types - rejected (loses per-type reviewability; harder to skip a type). A `seed` category - rejected (no new behavior warrants it).

### D6: The per-type analyze -> evaluate -> decide workflow
**Choice**: For each contract type, run A (analyze via Kimi, grounded in that type's legal nature + what 示范文本 typically omits) -> B (evaluate each candidate: 《法条》 real & current? non-redundant with base? real drafting signal?) -> C (decide: add the real ones, with stance variants only where the stance axis genuinely differs; else record in `skipped` with a reason). The `employment` manifest is the pilot.
**Rationale**: This is the core of the pivot - per-type, specific, honest. The skip list is what makes it "真实" (not padding to fill a quota).
**Alternatives**: Generate all manifests in one LLM call - rejected (loses per-type depth; dilutes). Skip the evaluate step - rejected (fabrication risk; violates 真实).

### D7: Kimi is the consultation model (豆包 deferred)
**Choice**: Per-type analysis consults Kimi (`kmodel_latest` via the `linjie.love` relay). 豆包 was unreachable through the configured `.env` (no doubao model on the relay; no Ark key; litellm proxy down).
**Rationale**: The user accepted Kimi as the consultation model. Re-running through litellm/doubao later is a verification option, not a blocker.
**Alternatives**: Wait for 豆包 - rejected (blocks progress; the employment pilot already produced strong, 法条-verified output via Kimi).

## Risks / Trade-offs

- **[41-type effort]** Each type = one Kimi consultation + a realness evaluation. Mitigation: the employment pilot validated the flow and output shape; the remaining ~40 can be batched (a workflow fan-out, with explicit opt-in) or run sequentially.
- **[Vocab growth]** Unreviewed type-specific dims could fragment facets. Mitigation: `register_tag_dim` is a code-change review gate (a dim enters the vocab only when added to `tags.py`); the manifests make each proposed dim reviewable.
- **[Tag drift vs body]** Editing a body to flip its effective stance leaves the `stance` tag stale (tags not re-derived). Mitigation: the edit form re-displays current tags beside the body so the operator can re-set them. Acceptable for v1 (curated, low volume).
- **[Pilot generalization]** `employment` is feature-rich; some types (e.g. `gift`, `bailment`) may yield only skips. That is correct behavior (真实), not a failure - the manifest records the skip with reasons.
- **[Assembly drops untagged custom clauses when `stance` set]** A custom clause left untagged is excluded when `stance` is requested. Mitigation: stance variants in the manifests are tagged; documented as opt-in filter behavior.
