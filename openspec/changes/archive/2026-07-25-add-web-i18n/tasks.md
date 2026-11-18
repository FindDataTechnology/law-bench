## 1. Translation source: `src/web/i18n.py`

- [x] 1.1 Create `src/web/i18n.py` with `SUPPORTED = ("zh", "en")`, `DEFAULT = "zh"`, and a `LOCALES` dict mapping each locale to a flat dotted-key → string catalog. Cover every current UI string, grouped by surface: `nav.*`, `h1.*`, `form.*` (labels, placeholders, buttons), `col.*` (table headers: name, context, source, criteria, contract_type, purpose, type, mode, created, label, rubric, n), `hint.*`, `flash.*` (rubric_created/updated/deleted, criterion_added/updated/deleted/moved, prompt_created/updated/deleted, harbor_refreshed/failed), `matrix.*` (criterion, view_draft, running, loading, empty_draft, no_reasoning, not_found, error_loading, cells_passfail, cells_passrate, legend, headline, meta, select_min), `crit_row.*` (new, name, description, guidance, remove), `switch.*` (en, zh)
- [x] 1.2 Author the `zh` catalog as the primary; author the `en` catalog to match the existing English strings exactly (status quo wording preserved)
- [x] 1.3 Add `resolve_locale(request) -> tuple[str, dict]`: `?lang` (validate against `SUPPORTED`) ▶ `lang` cookie ▶ `Accept-Language` first supported match ▶ `DEFAULT`; returns `(lang, t)` where `t = LOCALES[lang]`
- [x] 1.4 Add a `t_lookup(t, key, **fmt)` helper that does `t.get(key, key).format(**fmt)` so interpolated flashes resolve cleanly with a key fallback

## 2. Locale dependency + Jinja globals (`src/web/app.py`)

- [x] 2.1 Add a FastAPI dependency `get_locale(request)` that calls `resolve_locale`, sets the `lang` cookie on the response (so it persists), and returns `(lang, t)`. Wire it so every template render has `lang` and `t` available as Jinja globals (via `templates.env.globals` or a dependency injected into each `TemplateResponse` context)
- [x] 2.2 Set `<html lang="{{ lang }}">` in `templates/base.html`
- [x] 2.3 Verify the JSON API (`/api/*`) is unaffected - locale resolution runs for HTML routes only and never alters API payloads or error JSON

## 3. Templates: chrome + table headers (`templates/*.html`)

- [x] 3.1 `base.html`: replace nav labels (Rubrics/Prompts/Compare/+ New local rubric/Re-extract harbor), brand text, and flash wrapper with `{{ t.<key> }}` lookups; flash renders via `{{ t_lookup(t, request.query_params.get('msg')) }}` (key → localized, unknown → raw passthrough)
- [x] 3.2 `rubrics_list.html`: localize h1, button, table headers (Name/Context/Source/Criteria), empty-state hint, and the trailing hint paragraph
- [x] 3.3 `prompts_list.html`: localize h1, button, headers (Name/Contract type/Purpose/Type/Source), empty-state, trailing hint
- [x] 3.4 `compare_list.html`: localize h1, button, headers (#/Label/Contract type/Rubric/Mode/N/Created), empty-state, trailing hint
- [x] 3.5 `rubric_form.html` / `prompt_form.html` / `compare_form.html`: localize headings, field labels, placeholders, submit/cancel buttons, and the criterion-row labels (Name/Description/Guidance) used by the dynamic editor
- [x] 3.6 `rubric_detail.html` / `prompt_detail.html` / `compare_detail.html`: localize headings, section labels, action buttons (edit/delete/add criterion/move up/move down), and the `Loading compare…` placeholder in `compare_detail.html`
- [x] 3.7 Sweep all templates for any remaining hard-coded English UI literal (grep for `>[A-Z][a-z]+` in tag text and `placeholder=`/`value=` attributes) and convert; confirm zero English chrome remains

## 4. Flash messages: emit keys (`src/web/routes/pages.py`)

- [x] 4.1 Change `_flash(path, msg, err, status)` to accept a message key (e.g. `"flash.rubric_created"`); keep the redirect URL shape `?msg=<key>[&err=1]`
- [x] 4.2 Update every `_flash(...)` call site to pass the catalog key instead of a literal string
- [x] 4.3 For interpolated flashes (`Prompt {name!r} deleted.`, `Rubric {name!r} deleted.`, `Harbor extraction failed: {err}`): store the template under `flash.prompt_deleted` / `flash.rubric_deleted` / `flash.harbor_failed` in each locale, and format with `t_lookup(t, key, name=..., err=...)` at flash-generation time using the route's resolved locale
- [x] 4.4 For dynamic error text that is not a catalog key (rare), pass the raw string through; confirm `t_lookup`'s key-fallback renders it unchanged
- [x] 4.5 Confirm the JSON API error payloads (`/api/*`) are unchanged - only HTML flashes are affected

## 5. Language switcher + client bootstrap (`templates/base.html`)

- [x] 5.1 Add an `EN | 中文` switcher to `base.html`'s topbar `<nav>`: two `<a>` links pointing to the current path with `?lang=en` and `?lang=zh` (preserve other query params where reasonable); mark the active locale's link `aria-current="page"`
- [x] 5.2 Add `<script>window.__LOCALE__ = {{ t|tojson }}; window.__LANG__ = "{{ lang }}";</script>` before the `app.js` include so the client catalog is available
- [x] 5.3 Verify the switcher round-trips: clicking a link sets the cookie (via the dependency) and the page re-renders in the chosen locale

## 6. Client matrix (`static/app.js`)

- [x] 6.1 At the top of `app.js`, read `const L = window.__LOCALE__ || {}; const LANG = window.__LANG__ || 'en';` and define a small accessor `function tr(key, fallback)` returning `L[key] || fallback || key`
- [x] 6.2 Localize `makeCriterionRow()`: `New criterion`, `Name`, `Description`, `Guidance`, `Remove` → `tr('crit_row.*', …)`
- [x] 6.3 Localize the compare matrix render: `<th>criterion</th>` → `tr('matrix.criterion')`, `view draft` buttons → `tr('matrix.view_draft')`, `Loading…` → `tr('matrix.loading')`, `(empty draft)` → `tr('matrix.empty_draft')`, `(no reasoning recorded)` → `tr('matrix.no_reasoning')`
- [x] 6.4 Localize status/meta/legend/headline strings: `Select at least 2 prompts.`, `Running compare… this may take a minute.`, `Error: `, the `meta.textContent` template, the `headline`/`legend` conditionals, `Compare #X was not found on the server.`, `Error loading compare (and no cached copy available).`, the draft modal title `Draft · `
- [x] 6.5 Confirm graceful degradation: with no `window.__LOCALE__`, `tr()` falls back to English literals so `app.js` never throws on a page missing the bootstrap

## 7. Tests + validation

- [x] 7.1 Catalog parity test: assert `set(LOCALES['zh'].keys()) == set(LOCALES['en'].keys())`
- [x] 7.2 Locale-resolution test: `?lang=en` over cookie `zh`; cookie honored when no param; `Accept-Language: en` on first visit; unknown `?lang=fr` falls back to `zh`
- [x] 7.3 Web-route test: a GET with `?lang=zh` sets the `lang` cookie and renders a localized table header (e.g. 名称); `?lang=en` renders `Name`
- [x] 7.4 Flash test: after creating a rubric, the redirect `?msg=flash.rubric_created` renders localized in the active locale (zh and en both checked); interpolated `flash.prompt_deleted` renders with the name substituted
- [x] 7.5 Switcher test: the topbar contains `?lang=en` and `?lang=zh` links and the active one is marked `aria-current`
- [x] 7.6 `app.js` parity: assert every key referenced by `app.js` (`matrix.*`, `crit_row.*`) exists in both catalogs
- [x] 7.7 Run `openspec validate add-web-i18n` and fix any reported gaps; run `openspec status --change add-web-i18n` to confirm artifact completion
