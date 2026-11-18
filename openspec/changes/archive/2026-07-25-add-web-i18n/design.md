## Context

The evaluation-rules web app (`src/web/`) is a FastAPI + Jinja2 server-rendered UI managing rubrics, prompts, and prompt-compares for a Chinese contract-drafting crew. Today every UI string is an English literal. The strings live in **three places**, not one:

1. **Jinja templates** (`templates/*.html`) - nav, headings, form labels, table column headers (`Name`, `Context`, `Source`, `Criteria`, `Contract type`, `Purpose`, `Type`, `Mode`, `Created`…), hints, button labels. ~60 strings.
2. **Python routes** (`routes/pages.py`) - flash messages emitted by `_flash(...)`: `"Rubric created."`, `"Criterion added."`, `"Prompt {name!r} deleted."`, `"Harbor extraction failed: …"`. ~12 strings, some interpolated. They are carried in the redirect URL as `?msg=…` and rendered by `base.html`.
3. **Client JS** (`static/app.js`) - the compare matrix is rendered client-side: `<th>criterion</th>`, `view draft` buttons, `"Running compare… this may take a minute."`, `"Loading…"`, `"Compare #X was not found on the server."`, plus the dynamic criterion-row template (`New criterion`, `Name`, `Description`, `Guidance`, `Remove`). ~15 strings.

The data underneath (rubric/prompt content) is mostly Chinese because the system drafts Chinese contracts; only the *chrome* is English. Locale is currently fixed (`<html lang="en">`).

## Goals / Non-Goals

**Goals:**
- One translation source of truth (`src/web/i18n.py`) feeding all three layers (templates, Python flashes, `app.js`).
- Support **zh** and **en**, default **zh** (product is a Chinese contract-drafting system).
- Per-request locale resolution with persistence (cookie), plus a visible `EN | 中文` switcher.
- Localize every UI string: chrome, table headers, flash messages, and the client-rendered matrix.
- Keep URLs locale-independent (flash carries a key, not a localized string).

**Non-Goals:**
- Multi-language *content* per record (branch B - a rubric/prompt having parallel zh+en variants). Out of scope; the data model is untouched.
- Languages beyond zh+en. The set is fixed for now; the design must not preclude adding a third later, but adding one is a follow-up.
- Localizing JSON API error payloads (`/api/*` `{"error": ...}`). Those remain as-is; only the HTML UI is localized.
- Localizing authored *data text* (rubric descriptions, prompt content). Those are stored and shown as-authored.
- A translation management UI or `.po`/`.mo` toolchain. The catalog is a Python dict edited in source.

## Decisions

### D1. Homegrown locale dict over Babel/Jinja-i18n or client-side-only
- **Chosen**: a plain Python dict `LOCALES = {"zh": {...}, "en": {...}}` in `src/web/i18n.py`, injected into templates as a `t` global and bootstrapped to `app.js` as `window.__LOCALE__`.
- **Alternative A**: Jinja2 i18n extension + Babel (`{% trans %}`, `_()`, `.po`/`.mo` catalogs, a compile step). Rejected - the catalog is ~90 strings; a build toolchain and `.po` round-trip is disproportionate, and bridging Babel's `gettext` into `app.js` is awkward.
- **Alternative B**: client-side-only i18n (`data-i18n` attributes + a JS dictionary). Rejected - doubles the string homes (server templates still need their own), and the server-rendered chrome would flash English before JS swaps it.
- The homegrown dict is one file, no build step, and reaches all three layers from one source.

### D2. One source of truth feeding three layers
- **Chosen**: `i18n.py` owns `LOCALES` + a `resolve_locale(request)` helper returning `(lang, t)`. Templates get `t`/`lang` via Jinja globals (set in `app.py`). `app.js` gets the same `t` via `base.html` injecting `<script>window.__LOCALE__ = {{ t|tojson }}; window.__LANG__ = "{{ lang }}";</script>`.
- **Alternative**: separate catalogs for server and client. Rejected - drift risk; the matrix labels and the table headers must agree.

### D3. Default `zh`; supported `{zh, en}`; resolution order `?lang` ▶ cookie ▶ `Accept-Language` ▶ `zh`
- **Chosen**: a FastAPI dependency reads `?lang=` (validated against `SUPPORTED`), then the `lang` cookie, then `Accept-Language` (first match in `SUPPORTED`, else `zh`). On any resolved locale it (re)sets the `lang` cookie so the choice persists.
- **Default `zh`**: the product drafts Chinese contracts; a Chinese-first chrome matches its users. `Accept-Language` is only consulted when neither `?lang` nor a cookie is present.
- **Alternative**: default `en` (status quo). Rejected by the product decision; the chrome should lead in Chinese.

### D4. Flash messages carry a **key**, not a localized string; resolved at render
- **Chosen**: `_flash(path, key, err=...)` writes `?msg=<key>` (e.g. `flash.rubric_created`). `base.html` renders the flash via `{{ t.get(msg, msg) }}` - if `msg` is a known key it translates; otherwise it shows the raw string (backward-compatible with any caller still passing a literal, and with dynamic error text like `"Harbor extraction failed: <stderr>"` which stays a literal). Interpolated flashes store a template (`flash.prompt_deleted = "Prompt {name!r} deleted."` / `"已删除提示词 {name!r}。"`) and are formatted with `.format(name=…)` at flash-generation time against the resolved locale's `t`.
- **Alternative**: translate at generation (route resolves locale, writes the localized string into the URL). Rejected - a bookmarked or stale URL would render in the wrong language; key-in-URL keeps URLs locale-independent and lets a locale switch re-render an existing flash.
- **Dynamic error text** (e.g. extraction stderr) remains a literal string in the URL; `t.get(msg, msg)` passes it through unchanged. Acceptable - these are rare, transient, and often contain tool output that has no translation.

### D5. `EN | 中文` switcher in the topbar, posting `?lang=`
- **Chosen**: two links in `base.html`'s `<nav>` (alongside `Rubrics`/`Prompts`/`Compare`), each an `<a href="?lang=en">` / `?lang=zh` on the current page. The active locale's link is marked `aria-current`. The resolution dependency sets the cookie on the resulting GET, then the page re-renders localized.
- **Alternative**: a `<select>` form. Rejected - heavier markup for a two-option toggle; plain links match the app's no-fancy-form style and are fully crawlable/no-JS.

### D6. `app.js` reads `window.__LOCALE__`; no fetch, no separate catalog
- **Chosen**: `base.html` bootstraps `window.__LOCALE__ = {{ t|tojson }}`. `app.js` defines `const L = window.__LOCALE__ || {}` and replaces every literal with `L.matrix.criterion`, `L.matrix.view_draft`, `L.matrix.running`, `L.matrix.loading`, `L.crit_row.name`, etc. The dynamic `makeCriterionRow()` template and the matrix `<th>`/`view draft` button all key off it.
- **Fallback**: `|| {}` and `L.x || '<english fallback>'` keep `app.js` from throwing if the bootstrap is absent (e.g. a page without `base.html`'s script), degrading to English rather than breaking.
- **Alternative**: fetch `/api/i18n?lang=zh` at runtime. Rejected - extra round-trip and a render-time flash of English; the bootstrap is already on every page via `base.html`.

### D7. No DB/schema change; data-model multi-language (branch B) out of scope
- **Chosen**: localization is presentation-only. No `lang` column, no translation table, no JSON blob.
- **Alternative**: a `rubric_translations`/`prompt_translations` table for parallel zh+en content per record. Rejected for this change - the user's "multi language with the table columns" resolves to **translating column headers** (branch A), not storing multi-language row data. Storing multilingual content is a possible follow-up and the design does not preclude it, but it is not built here.

### D8. `<html lang="{{ lang }}">` set dynamically
- **Chosen**: `base.html` uses `<html lang="{{ lang }}">` so screen readers, hyphenation, and browser translation hints follow the active locale. Cheap correctness win.
- **Key naming**: dotted hierarchical keys (`nav.*`, `col.*` for table headers, `form.*`, `flash.*`, `matrix.*`, `crit_row.*`, `hint.*`). Mirrors the existing string locations and groups naturally by surface.

## Risks / Trade-offs

- **[Catalog drift between zh and en]** -> A key added to `en` but forgotten in `zh` (or vice versa). Mitigation: `resolve_locale` returns a `t` that falls back to the key (or to `en`) when a zh key is missing, and a task adds a test asserting `set(en.keys()) == set(zh.keys())`.
- **[Stale `window.__LOCALE__` if a string is renamed]** -> `app.js` degrades to English via the `||` fallback rather than throwing. Mitigation: the parity test covers the client keys too.
- **[Flash error text is sometimes dynamic]** -> `t.get(msg, msg)` passes unknown messages through as-is, so tool stderr / unexpected strings still render (in English). Acceptable; documented in D4.
- **[Cookie-based locale can disagree with `Accept-Language` on first visit]** -> First visit with no cookie honors `Accept-Language`; once the user (or the resolution dep on a `?lang=`-less first hit) sets the cookie it sticks. Mitigation: the dependency always (re)sets the cookie to the resolved locale, so the system converges to a stable choice.
- **[Adding a 3rd language later]** -> The dict + `SUPPORTED` tuple make adding a locale a single-file edit plus translations; no schema or build change. Documented as easy in D7.

## Migration Plan

- **Deploy**: presentation-only, no data migration. Add `i18n.py`, wire the dependency into `app.py`, edit templates + `pages.py` + `app.js`, add the switcher and bootstrap script to `base.html`. First visit defaults to `zh`.
- **Rollback**: revert the file edits. No DB state to undo; existing data and API behavior are untouched throughout.
- **Validation**: a parity test (zh/en key sets equal) and a web-route test asserting (a) `?lang=zh` sets the cookie and renders a localized header, (b) a flash key renders localized, (c) `Accept-Language: en` with no cookie resolves to `en`.

## Open Questions

- **Key set granularity for table headers**: one `col.name` reused across every table, or per-table (`col.rubrics.name`, `col.prompts.name`) in case a future locale wants a different short label per table? Lean: shared `col.*` keys now (headers like "Name"/"Source" recur across tables); split only if a locale needs a per-table override.
- **Flash for `Accept-Language` mismatch on first visit**: should the first-visit locale be persisted immediately (cookie set on a `?lang`-less GET) or only when the user explicitly switches? Lean: persist immediately - it converges to a stable locale and avoids re-reading `Accept-Language` on every request.
