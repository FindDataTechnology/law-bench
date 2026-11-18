## Why

The evaluation-rules web app (`src/web/`) is server-rendered with hard-coded English UI strings: nav, headings, form labels, **table column headers** (`Name`, `Context`, `Contract type`, `Criteria`…), flash messages born in Python (`pages.py`), and the client-rendered compare matrix in `app.js`. The product underneath is a Chinese contract-drafting system, so an English-only chrome is a poor fit for its users. This change adds **zh/en** multi-language support to the web UI, defaulting to **zh**, with a single translation source feeding templates, Python routes, and `app.js`.

## What Changes

- **New `src/web/i18n.py`**: the single source of truth - a `LOCALES` dict keyed by locale code (`zh`, `en`) mapping dotted message keys (`nav.rubrics`, `col.name`, `flash.rubric_created`, `matrix.criterion`, …) to localized strings. Declares `SUPPORTED = ("zh", "en")` and `DEFAULT = "zh"`.
- **Locale resolution dependency** in `src/web/app.py` (FastAPI dependency / Jinja global): resolves the active locale per request as `?lang=` ▶ `lang` cookie ▶ `Accept-Language` ▶ `zh`, sets the `lang` cookie so the choice sticks, and exposes `t` (the resolved dict) and `lang` to every template.
- **Templates (`templates/*.html`)**: replace hard-coded English chrome with `{{ t.<key> }}` lookups (nav, headings, form labels, **table headers**, hints, buttons); `base.html` sets `<html lang="{{ lang }}">` and adds an `EN | 中文` language switcher to the topbar.
- **Flash messages (`routes/pages.py`)**: `_flash(...)` emits a **message key** (e.g. `flash.rubric_created`) in the redirect URL instead of a localized string; `base.html` resolves the key against `t` at render time, so URLs are locale-independent and a stored-language change re-renders correctly. Interpolated messages (`flash.prompt_deleted` with `{name}`) use `str.format` against the localized template.
- **Client matrix (`static/app.js`)**: `base.html` bootstraps `window.__LOCALE__ = {{ t|tojson }}` (and `window.__LANG__`); `app.js` replaces its literals (`criterion`, `view draft`, `Running compare…`, `Loading…`, the dynamic criterion-row labels) with `window.__LOCALE__.<key>` lookups. No extra fetch.
- **No schema/DB changes**. Multi-language *content* per record (branch B - a rubric/prompt having parallel zh+en variants) is explicitly out of scope.

## Capabilities

### New Capabilities
- `web-i18n`: multi-locale (zh/en) presentation layer for the evaluation-rules web app - supported locales with zh default, per-request locale resolution with persistence, a language switcher, and localized rendering of all UI chrome (nav, headings, form labels, table headers, hints), flash messages (key-based), and the client-rendered compare matrix.

### Modified Capabilities
<!-- None. The existing web specs (evaluation-rules-web, generation-prompts-web, prompt-compare-web) describe list/form/detail behavior, which is unchanged; localization of the chrome is owned by the new web-i18n capability and does not alter those requirements. -->

## Impact

- **New code**: `src/web/i18n.py` (locale dict + resolver); a locale dependency wired into `src/web/app.py` (Jinja globals + cookie); an `EN | 中文` switcher in `templates/base.html`.
- **Modified code**: all `templates/*.html` (string → key lookups); `src/web/routes/pages.py` (`_flash` emits keys, interpolated flashes use `.format`); `static/app.js` (literal → `window.__LOCALE__` lookups); `base.html` (`<html lang>`, bootstrap script).
- **Reused as-is**: `src/eval/*`, the DB schema, the manage layer, all API JSON behavior. No data-model change.
- **Dependencies**: none new (FastAPI, Jinja2 already in use; no Babel/gettext, no build step).
- **Operations**: none - no seeding, no migration. Locale defaults to `zh` on first visit.
- **Out of scope**: multi-language *content* storage per record (branch B); adding languages beyond zh/en; localizing the JSON API error payloads (those remain as-is); localizing the contract/prompt *data text* (authored per-row, untouched).
