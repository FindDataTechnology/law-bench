## Why

The clause knowledge base (`add-clause-knowledge-base` + `add-clause-admin-dashboard`) tags every clause along *fixed, derivable* dimensions only: `contract_type` (41 types), `category` (base/tagged/custom), `section` (10 chapters), `province`, `level`. These answer "what contract / which chapter / which province" but **not** the questions that drive clause selection when drafting or risk-reviewing - and, critically, the dimensions that matter **differ by contract type**. A 对赌 mechanism is specific to `vam_agreement`; 竞业限制 / 服务期 / 工时 are specific to `employment`; 背景IP / 衍生IP are specific to `technology` / `software_development`. A single "big-and-comprehensive" (大而全) universal tag set + universal seed pool would either miss these type-specific signals or pad every type with irrelevant clauses.

This change takes the opposite approach: **per-contract-type, specific** tags and clauses, discovered by running an **analyze → evaluate → decide** flow over each of the 41 types, with **honest skip** when a type has nothing genuinely new. A pilot on `employment` (consulting Kimi, 2026-07-30) validated the flow: it produced 2 labor-specific tag dimensions (特殊约束期属性, 工时制度类型), 4 type-specific clauses with verified 《法条》 (§22 / §23-24 / §39+劳部发503号 / §4), and 4 honest skips with statutory reasons (试用期 / 报酬 / 社保 / 劳动保护 - all 法定强制 or 必备条款 already in base). Two AIs (Claude + Kimi) were consulted; 豆包 was unreachable via the configured relay and is deferred - Kimi adopted as the consultation model.

## What Changes

- **Growable tag vocabulary** (`src/clauses/tags.py`): a controlled vocabulary that starts with a minimal universal starter set (`stance`, `strength`, `risk`, `mandatory`) and **grows** as per-type analysis proposes type-specific dimensions (e.g. `special_restriction_period`, `working_hours_system` for `employment`; `vam_mechanism` for `vam_agreement`). New dimensions are added only after review; `validate_tags` drops unknown keys and rejects out-of-vocabulary values.
- **`tags` JSONB column** on `clauses` (additive `ALTER` via `_ADDITIVE_COLUMNS`): stores the validated tag object. Defaults `'{}'`; **not** body-derived (curatorial).
- **Per-type seed manifest**: `data/clause_seeds/<contract_type>.yaml`, one per type, holding `{tags: [...type-specific dims...], clauses: [...], skipped: [{item, reason}]}`. Each clause carries **real 《法条》** (article numbers, no fabrication), `{{slot}}` placeholders, and a `section` from the canonical 10. The `skipped` list is a first-class output proving the flow ran and did not pad.
- **Seed loader** (`scripts/seed_stance_clauses.py`): reads the manifests and loads clauses as `category=custom, manual=true`, idempotent via a `source_doc_title='seed:<contract_type>'` marker (delete-then-insert). Stance variants are produced only where the type's analysis found a real stance axis.
- **Dashboard tagging + facets**: create/edit forms gain tag dropdowns (driven by the current vocabulary); browse filters by tags.
- **Assembly by stance**: `generate_contract_assembled(..., stance=None)` optionally filters custom clauses to a stance.
- **The per-type analysis run** (execution, not application code): for each of the 41 contract types, run A (analyze via Kimi) → B (evaluate: 《法条》 real & current? non-redundant with base? real signal?) → C (decide: add if real, else skip with reason). The `employment` manifest is the pilot; the remaining ~40 are produced by the same flow.
- **No changes** to extraction (tags not set there), `document-generation`, or `contract-templates`.

## Capabilities

### New Capabilities
- `clause-custom-tags`: a growable-vocabulary tag layer over `clauses`, set via the dashboard, browsed as facets, usable as an assembly filter - fed by per-contract-type seed manifests (analyze → evaluate → decide, with honest skip) rather than a universal pool.

### Modified Capabilities
<!-- None (additive hooks into clause-admin create/edit and clause-knowledge-base assembly; no existing requirement is altered). -->

## Impact

- **New code**: `src/clauses/tags.py`; `src/clauses/seed_manifest.py` (manifest read/validate); `scripts/seed_stance_clauses.py`; `data/clause_seeds/*.yaml`; template changes for tag dropdowns/facets/chips.
- **New tests**: `tests/test_clauses_tags.py`, `tests/test_clauses_seed_manifest.py`, `tests/test_clauses_assemble_stance.py`.
- **Modified code**: `src/eval/store.py` (additive `tags` column); `src/clauses/store.py` (carry `tags`); `src/clauses/assemble.py` (`stance`); `src/web/routes/clauses.py` (facets + fields + `stance`); `src/clauses/__init__.py`; `src/clauses/cli.py` (`--stance`).
- **Dependencies**: `pyyaml` for manifest parsing (add to `pyproject.toml` if not already a transitive dep).
- **Data**: additive `tags jsonb` (default `'{}'`); per-type seed manifests under `data/clause_seeds/`.
- **Operations**: tags set via the dashboard; seed clauses loaded once per type via the CLI script.
- **Out of scope**: a universal seed pool (rejected), free-form tags (controlled vocab), an LLM auto-tagger, clause versioning, and the optional `compliance`/`negotiability` dimensions (follow-up change).
