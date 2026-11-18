## Why

When the active locale is `zh`, the 评估规则 (rubrics) pages still render large amounts of English. The biggest offender is the rubric **detail** page: every criterion's `name` (a snake_case machine key like `party_identification`) is shown raw as the criterion heading. This affects two criterion sources - the harbor-seeded criteria (full English prose from `src/eval/seed/harbor/*.toml`) and the contract-seeded criteria (`scripts/seed_contract_rubrics.py`, whose description/guidance are already Chinese but whose `name` heading is English, with `PASS if` / `FAIL if` tokens in the guidance). The `source` field renders raw (`harbor:vX.Y.Z` / `local`), and the add-criterion form carries a hard-coded `e.g. party_identification` placeholder. The existing i18n layer localizes UI chrome and a fixed set of data-label kinds (`contract_type`, `purpose`, `prompt_type`, `context`, `mode`) but has no coverage for criterion content or source values, so these data items fall straight through to English.

## What Changes

- **Localize seeded criterion content.** Add a `zh` translation catalog keyed by criterion `name`: full title/description/guidance for the harbor criteria, and zh titles for all contract-seeded criteria (their description/guidance are already Chinese in the DB). A `criterion_for` resolver falls back to the stored DB text for unmapped or user-authored criteria and for the `en` locale. Wire `rubric_detail.html` to render localized criterion title / description / guidance.
- **Localize guidance `PASS if` / `FAIL if` tokens.** For `zh` guidance with no catalog entry, translate the stored `PASS if` / `FAIL if` tokens to `通过条件：` / `不通过条件：` (matching the form-label convention), so the contract criteria render fully in Chinese without per-criterion guidance translations.
- **Localize the `source` display.** Add a `source_label` resolver: `local` -> 本地 / local, `harbor:vX.Y.Z` -> `Harbor v{ver}`, raw fallback otherwise. Use it for the harbor badge (list + detail), the detail `source` row, and the readonly-note source.
- **Remove hard-coded English placeholders.** Replace the literal `e.g. party_identification` placeholder in `rubric_detail.html` and in `app.js` (`makeCriterionRow`) with catalog-backed strings.
- **Keep the architecture intact.** No new localization mechanism: extend the existing data-label tier (catalog + resolver + raw fallback) and the chrome catalog. Parity and fallback contracts are preserved; harbor seed TOMLs remain the canonical English source; no DB schema change.

## Capabilities

### New Capabilities
<!-- None - this extends existing localization and rubrics-web capabilities. -->

### Modified Capabilities
- `web-i18n`: add requirements for localized criterion content (raw-key fallback to stored text), localized guidance `PASS if`/`FAIL if` tokens, and localized source display; tighten the no-hard-coded-English rule to cover input placeholders.
- `evaluation-rules-web`: refine the Browse and Detail requirements so criterion name / description / guidance and the source value render in the active locale where a translation exists, falling back to stored text.

## Impact

- `src/web/i18n.py` - new criterion-content catalog (harbor full zh + 206 contract zh titles) + `criterion_for` resolver (with guidance-token localization); new `source_label` resolver; new chrome keys for the placeholder strings; extend the parity / completeness test surface.
- `src/web/app.py` - expose the new resolvers as template globals bound to the active locale.
- `src/web/templates/rubric_detail.html`, `rubrics_list.html` - render localized criterion content and source labels; replace the hard-coded placeholder.
- `src/web/static/app.js` - replace the hard-coded placeholder in `makeCriterionRow`.
- `tests/test_i18n.py` - cover criterion-content fallback, contract-title completeness, guidance-token localization, source labels, and the new placeholder keys; keep parity assertions green.
- No DB schema change; harbor seed TOMLs and the contract seed script stay the canonical sources.
