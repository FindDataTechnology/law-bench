## Context

The web app has a mature two-tier i18n layer in `src/web/i18n.py`:

1. **Chrome catalog** (`LOCALES`, zh/en) - UI strings (nav, headings, labels, hints, buttons, flash, matrix). Parity between zh and en key sets is asserted by `tests/test_i18n.py`.
2. **Data-label catalog** (`LABELS`, zh/en) - machine keys stored in the DB (`contract_type`, `purpose`, `prompt_type`, `context`, `mode`) resolved to display labels by `label_for()`, plus `title_for_prompt` / `title_for_rubric` for seeded-name display titles. Resolution always falls back to the raw key for unmapped / user-authored values - never raises, never blanks. The machine key stays the canonical DB / URL / join identifier.

`app.py::_locale_context` exposes the active locale, both catalogs (pre-serialized as `t_json` / `labels_json`), and locale-bound resolvers (`label_for`, `title_for_*`, `tr`) as Jinja globals, and bootstraps `window.__LOCALE__` / `window.__LABELS__` / `window.__LANG__` for `app.js`.

The 评估规则 (rubrics) pages are `rubrics_list.html`, `rubric_detail.html`, `rubric_form.html` (routes in `src/web/routes/pages.py`). Harbor-seeded rubrics and their criteria come from English TOMLs under `src/eval/seed/harbor/` (`task_quality.toml`, `trial_behavior.toml`) and are stored verbatim in SQLite.

**The gap:** the data-label tier covers short enum-like keys but has no coverage for (a) criterion content (`name` / `description` / `guidance` prose) or (b) the `source` field. So on the rubric detail page - the data-richest page - every harbor criterion renders its raw English name/description/guidance, the `source` renders raw (`harbor:v0.4.2` / `local`), and an add-criterion input carries a hard-coded `e.g. party_identification` placeholder (`rubric_detail.html:98` and the matching `app.js` `makeCriterionRow`). Switching to `zh` leaves these untouched.

## Goals / Non-Goals

**Goals:**
- Render harbor-seeded criterion `name` / `description` / `guidance` in `zh` on the rubrics pages, with raw-stored-text fallback for `en` and for any unmapped / user-authored criterion.
- Render the `source` field as a localized label on the rubrics list and detail pages.
- Eliminate the hard-coded English placeholders (server- and client-side).
- Reuse the existing data-label tier (catalog + resolver + raw fallback); preserve parity / fallback contracts; no DB schema change; harbor TOMLs remain the canonical English source.

**Non-Goals:**
- Localizing criterion content in the **compare matrix** (`app.js` `renderMatrix`). The user's report is scoped to the 评估规则 page; the compare page is a separate capability and its criterion rendering can be extended later.
- Locale-formatting `created_at` (raw ISO-8601 is not "English"; defer).
- Translating user-authored local-rubric content (it is locale-agnostic free text; fallback handles it).
- Any change to harbor seeding, the DB schema, or the JSON API payloads (API keeps raw machine values; localization is a presentation-layer concern).

## Decisions

### Decision 1: Extend the data-label tier for criterion content; do not add a new mechanism
Add a dedicated `CRITERION_I18N` catalog and a `criterion_for(name, field, lang, fallback)` resolver in `i18n.py`, used by `rubric_detail.html`. The resolver returns the localized `title` / `description` / `guidance` when `(name, field)` is present for the active locale, otherwise returns `fallback` (the raw stored value).

**Why a separate catalog, not folding into `LABELS`:** `LABELS` is governed by `label_catalog_parity()` (zh and en MUST expose identical key sets) and stores short labels. Criterion content is long prose, and the `en` side is already the canonical English stored in the DB / TOMLs - duplicating it into an `en` catalog would create two sources of English truth that can drift. A separate `CRITERION_I18N` that carries only the `zh` translations (with `en` and unmapped falling back to stored text) avoids duplication and avoids entangling the parity contract.

**Alternatives considered:**
- *Store zh translations in the DB (new columns / JSON blob on criteria).* Rejected: schema migration + seed-loader changes + CRUD changes; the TOMLs are the canonical English source and translations are a presentation concern, not data.
- *Key the catalog by `(rubric_name, criterion_name)` instead of `name` alone.* Rejected as premature: the two seeded TOMLs use globally-distinct criterion names. Keying by `name` mirrors the existing `label_for` / `title_for_*` single-key pattern. (See Risks for the collision case.)

### Decision 2: `source_label` resolver
Add `source_label(source, lang) -> str` in `i18n.py`:
- `source == "local"` -> localized local label (`本地` / `local`), reusing the existing `badge.local` chrome concept but as a data resolver so the detail `source` row (not just the badge) is covered.
- `source` matches `^harbor:v(.+)$` -> `Harbor v{ver}` (proper noun, locale-independent).
- otherwise -> raw `source` unchanged.

Used in `rubrics_list.html` (harbor badge) and `rubric_detail.html` (badge + `source` dd).

### Decision 3: Placeholder strings in the chrome catalog
Add chrome keys `detail.criterion_name_placeholder` and `crit_row.name_placeholder` (zh `如：party_identification`, en `e.g. party_identification`). `rubric_detail.html` renders `{{ t.detail.criterion_name_placeholder }}`; `app.js` `makeCriterionRow` reads `tr('crit_row.name_placeholder', 'e.g. party_identification')`. This satisfies the existing "no hard-coded English UI string" rule and keeps the client/server catalogs in parity.

### Decision 4: Expose resolvers as locale-bound Jinja globals; no new bootstrap for criterion content
Add `criterion_for` and `source_label` to `_locale_context` bound to the active `lang` (mirroring `label_for` / `title_for_*`). No new `window.__*__` bootstrap is needed because criterion rows on the rubric detail page are server-rendered; only the add-criterion placeholder is client-side, and that uses the existing `window.__LOCALE__` via `tr()`.

### Decision 5: Completeness test against harbor seeds
Add a test that loads every criterion `name` from the harbor seed TOMLs and asserts each has a `zh` entry in `CRITERION_I18N`. This makes a future harbor seed that adds a criterion without a translation fail CI rather than silently leaking English.

## Risks / Trade-offs

- **[Criterion-name key collision]** A future harbor seed could reuse a `name` with different prose, making a single-key catalog ambiguous. -> *Mitigation:* current seeds are globally name-distinct; the completeness test documents the assumption; the fallback renders raw for any unmapped name. If a real collision arises, escalate to `(rubric_name, name)` keying then.
- **[Translation drift]** Harbor TOMLs gain a criterion but `CRITERION_I18N` is not updated -> silent English leak. -> *Mitigation:* the completeness test (Decision 5) fails CI. English-text drift (TOML prose edited) is lower-risk because the `en` side is the stored DB value itself, not a duplicated catalog entry.
- **[en locale depends on stored English]** For `en`, criterion content comes from the DB (English for harbor seeds). A local rubric storing Chinese content would show Chinese under `en`. -> *Accepted:* user-authored content is locale-agnostic; this matches the existing fallback philosophy for `prompt_type` etc.
- **[`source_label` Harbor proper noun is locale-independent]** `Harbor v0.4.2` is not translated. -> *Accepted:* "Harbor" is a product name; only the `local` label is translated.

## Migration Plan

- Code-only change; no DB migration, no harbor re-extraction required (translations live in the code catalog, not the DB).
- Deploy: ship the `i18n.py` / template / `app.js` / test changes together.
- Rollback: revert the commit; rendering returns to today's raw-English behavior with no data side-effects.

## Open Questions

- Should the compare matrix later adopt `criterion_for` for its criterion titles? (Deferred - out of scope for this change; tracked as a follow-up.)
- Should `created_at` get locale-aware formatting? (Deferred - not an English-leak issue.)
