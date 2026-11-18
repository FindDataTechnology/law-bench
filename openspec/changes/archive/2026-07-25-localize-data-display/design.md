## Context

The evaluation-rules web app is a Chinese legal contract tooling UI. It already has a mature i18n layer (`src/web/i18n.py`, spec `web-i18n`) that localizes all **UI chrome** - nav, headings, column headers, form labels, flash, and the compare matrix chrome - into `zh` (default) and `en`, resolved per request (`?lang` ▶ cookie ▶ `Accept-Language` ▶ `zh`) and bootstrapped to the client as `window.__LOCALE__`.

What is **not** localized is the **data** rendered inside those localized columns. Seed data stores machine-readable English keys: prompts (`name = draft_sale`, `contract_type = sale`, `purpose = drafting`, `prompt_type = baseline`), rubrics (`name = contract_sale_v1`, `context = contract`), and compares (`mode = drafter-only`, `rubric_name = contract_sale_v1`). The templates render these raw (`<code>{{ p.contract_type }}</code>` → `sale`), so a Chinese user sees English slugs inside Chinese chrome. Form placeholders are English too (`e.g. sale`, `e.g. drafting`, `e.g. party_identification`).

These English keys are load-bearing: `name` is the URL path (`/prompts/{name}`) and the FK-free join key that compares use to reference prompts and rubrics (`compare.rubric_name`, prompt names in `compare_runs`). The seed scripts are idempotent upserts keyed on `name`. So changing the stored values would require migrating rows and rewriting compare references - high risk, low benefit.

**Decision (confirmed with user):** display-layer localization. Keep all English keys as the canonical DB / URL / join identifiers; add a label catalog + resolver so the UI *renders* them in the active locale, with raw-key fallback for anything unmapped.

## Goals / Non-Goals

**Goals:**
- Render `contract_type`, `purpose`, `prompt_type`, `context`, and compare `mode` values in the active locale across all web templates and the client-rendered compare matrix.
- Render a localized **display title** for seeded prompt and rubric names (`draft_sale` → `买卖合同起草`; `contract_sale_v1` → `买卖合同评价规则`), keeping the machine `name` as the underlying identifier.
- Localize form placeholders from English examples to Chinese examples.
- Bootstrap the label catalog to the client (`window.__LABELS__`) so `app.js` localizes the matrix meta line and prompt/rubric labels.
- Fall back to the raw key for any unmapped or user-authored value (never blank).
- Keep the JSON API unchanged (raw machine keys).

**Non-Goals:**
- No DB migration, no schema change, no change to stored values, URLs, or join keys.
- No change to the JSON API contracts (localization is presentation-only).
- **Criterion names** (`party_identification`, `ownership_transfer`, …) are **not** localized in this change - their Chinese `description` and `guidance` already render directly below the name and are the substantive content. (Open Question: defer to a follow-up if needed.)
- No translation of arbitrary user-authored free-text names beyond the seeded naming conventions.
- No new locales (still `zh`/`en`).

## Decisions

### Decision 1: Display-layer mapping, not data migration
Keep English machine keys as DB/URL/join identifiers; localize only the rendered display via a catalog + resolver.

**Alternatives considered:**
- *Migrate stored data to Chinese* (store `name = 买卖合同起草`, `contract_type = 买卖合同`): rejected - renames break the FK-free joins in existing compares (orphaned `compare.rubric_name`), make URLs Chinese-percent-encoded, and require a migration with no rollback benefit. The user explicitly chose the display-layer approach.

### Decision 2: Catalog lives in `src/web/i18n.py`, not a new module
Add a `LABELS` dict (zh/en) and `label_for(kind, value, lang=None)` to the existing `src/web/i18n.py` - the declared "single source of truth" for presentation strings. Same module, same parity test, same bootstrap path.

**Alternatives considered:**
- *New `src/web/labels.py` module*: rejected - creates a second source of truth for localization, splits the parity test, and gains nothing (the i18n module already imports nothing heavy). Keep it co-located.

### Decision 3: One resolver, keyed by `kind`
`label_for(kind, value, lang)` where `kind ∈ {contract_type, purpose, prompt_type, context, mode}`. It walks `LABELS[lang][kind]` and returns the mapped label, or the raw `value` unchanged if unknown. Mirrors the existing `translate(t, key, **fmt)` walker pattern.

**Alternatives considered:**
- *Per-kind functions* (`contract_type_label(value)`, …): rejected - repetitive; one catalog + one resolver is simpler and extends by adding a `kind` key.
- *A single flat namespace*: rejected - `kind` buckets avoid collisions (e.g. a `context` value `contract` vs a `mode` value) and make the catalog readable.

The contract-type catalog mirrors the 19 民法典 types already used by the seed scripts (`sale`→买卖合同, `loan`→借款合同, `lease`→租赁合同, …, `partnership`→合伙合同) - the authoritative source is `chinese_contracts_class.md` and the seed script comments.

### Decision 4: Display titles derived from seed naming conventions
For the **prompt/rubric name** column (the primary link text and page heading), derive a localized display title from the seed name pattern, falling back to the raw name:

- Prompt `draft_<type_key>` → `label_for('contract_type', <type_key>)` + `起草` (e.g. `draft_sale` → `买卖合同起草`).
- Rubric `contract_<type_key>_vN` → `label_for('contract_type', <type_key>)` + `评价规则` (e.g. `contract_sale_v1` → `买卖合同评价规则`).
- Any name not matching these patterns → the raw `name` (user-authored names, including ones the user already typed in Chinese, pass through).

The machine `name` remains the link `href` and the `<code>` secondary where useful (e.g. URL is still `/prompts/draft_sale`). A small `title_for_prompt(name)` / `title_for_rubric(name)` helper in `i18n.py` encapsulates the parse + lookup.

**Alternatives considered:**
- *Add a `display_name`/`title` column*: rejected - schema change, against non-goals, and seed scripts would need updating.
- *Derive purely from `contract_type` without name-pattern matching*: rejected for rubrics (they have no `contract_type` field - the type is encoded only in the name), and rejected for prompts because it would lose the `起草` vs `评价规则` distinction.
- *Localize via the existing chrome `translate()`*: rejected - names aren't dotted keys in `LOCALES`; they're data values needing a different resolution path.

### Decision 5: Localize placeholders in-template, not via catalog
Form placeholders are example text (`e.g. sale` → `如：买卖合同`), not data. Hard-code the Chinese examples directly in the templates (with `lang`-conditional text if an English example is still wanted for `en`). Avoids catalogging throwaway example strings.

### Decision 6: Client bootstrap mirrors the chrome pattern
`_locale_context` (in `src/web/app.py`) already injects `t`, `t_json`, `lang`, `tr`. Extend it to also inject `labels` (active-locale `LABELS`), `labels_json`, and `label_for` (bound to the active locale). `base.html` already bootstraps `window.__LOCALE__ = t_json` and `window.__LANG__`; add `window.__LABELS__ = labels_json` alongside. `app.js` reads `window.__LABELS__` for the matrix meta (`{ct} · {rubric} · {mode} · N={n}`) and any prompt/rubric labels it renders, degrading to the raw key if the bootstrap is absent (same graceful-degradation contract as the chrome catalog).

**Alternatives considered:**
- *Re-derive labels in JS from a duplicated map*: rejected - duplication; the bootstrap keeps Python the single source.

### Decision 7: API unchanged
JSON endpoints (`/api/prompts`, `/api/rubrics`, `/api/compare`) continue to return raw machine keys. Localization is a template/client concern. This keeps the API machine-readable and scriptable.

## Risks / Trade-offs

- **[Display-title derivation couples to seed naming conventions]** If seed script naming changes (`draft_<key>` / `contract_<key>_vN`), titles revert to raw names silently. → *Mitigation:* derivation falls back to raw `name` on any non-match (never blanks); tests assert the seed names map correctly; a comment in the seed scripts notes the convention is relied upon by `title_for_*`.
- **[User-authored names show raw]** A user who creates a prompt named `my_custom` sees `my_custom`, not a translation. → *Accepted trade-off:* arbitrary free text cannot be translated; the user can type a Chinese name, which passes through unchanged.
- **[Criterion names remain English]** `party_identification` etc. still show in `rubric_detail.html` and the matrix first column. → *Accepted (Non-Goal):* the Chinese `description`/`guidance` render directly below and carry the substance; criterion-name catalogging is deferred (see Open Questions).
- **[Two catalogs to keep in parity]** `LOCALES` (chrome) and `LABELS` (data) both need zh/en key parity. → *Mitigation:* both live in `i18n.py`; extend `tests/test_i18n.py` parity assertions to `LABELS`.
- **[Client must degrade gracefully]** If `window.__LABELS__` is missing (stale cached `app.js`, partial render), the matrix must not break. → *Mitigation:* `app.js` already degrades to English for the chrome catalog; replicate that guard for labels (raw-key fallback).

## Migration Plan

None. This is a pure presentation-layer addition: new catalog + resolver in `i18n.py`, extended context processor in `app.py`, template edits, `app.js` edits, and tests. No DB migration, no stored-value changes, no URL changes, no API contract changes.

**Rollback:** revert the `i18n.py` / `app.py` / template / `app.js` / test changes. Data and joins are untouched, so rollback is clean and immediate with no data consequences.

## Open Questions

1. **Criterion-name localization?** Defer to a follow-up, or include a `criterion` kind catalog now? Suggested: defer - descriptions are already Chinese and carry the substance; only do it if users find the English criterion slugs distracting in the matrix.
2. **English (`en`) catalog values?** For `en`, should `contract_type` map to `Sale` / `Loan` (title-cased English) or pass through the raw lowercase key? Suggested: provide proper English labels (`Sale`, `Loan`, `Drafting`, `Drafter-only`) so both locales are fully readable, matching how `web-i18n` provides real English chrome rather than pass-through.
