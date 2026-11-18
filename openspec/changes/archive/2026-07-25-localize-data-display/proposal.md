## Why

The web app already localizes all UI chrome (nav, headings, column headers, buttons, flash) via the `web-i18n` layer, but the **data values** rendered inside those columns are still raw English machine keys: the prompts list shows `name = draft_sale`, `contract_type = sale`, `purpose = drafting`; rubrics show `contract_sale_v1`, criterion `party_identification`; compares show `drafter-only` and `sale`. A Chinese-speaking user opening the 评估规则 / 提示词 / 对比 pages sees a wall of English slugs where they expect 买卖合同 / 起草 / 买卖合同起草. The app feels half-localized: Chinese chrome wrapping English data. We need to extend the localization layer to cover these data-value displays so the content the user actually reads is Chinese.

## What Changes

- Add a **data-label catalog** (zh/en) for the known enum-like keys: the 19 民法典 contract types (`sale` → 买卖合同), `purpose` (`drafting` → 起草), `prompt_type` (`baseline` → 基线), `context` (`contract` → 合同), and compare `mode` (`drafter-only` → 仅起草).
- Add a **`label_for(kind, value, locale)` resolver** with **fallback to the raw value** for unknown / user-authored keys (so free-text names that aren't in the catalog still render, not blank).
- Add **localized display titles** for seeded prompt / rubric / criterion names (e.g. prompt `draft_sale` → 买卖合同起草; rubric `contract_sale_v1` → 买卖合同评价规则). The machine `name` remains the stable identifier used in URLs and FK-free joins (compares reference `rubric_name` / prompt names); only the *display* is localized.
- **Localize form placeholders** from English examples (`e.g. sale`, `e.g. drafting`, `e.g. party_identification`) to Chinese examples (`如：买卖合同`, `如：起草`, `如：主体识别`).
- **Bootstrap the label catalog to the client** (`window.__LABELS__`) so `app.js` localizes the compare matrix meta (`{ct} · {rubric} · {mode} · N={n}`) and prompt/rubric labels rendered client-side.
- Apply the resolver across the affected templates: prompts list / detail / form, rubrics list / detail / form, compare form / list / detail matrix.
- **No storage or schema change.** English keys stay as the canonical DB values and join keys; nothing migrates, nothing breaks existing compares.

## Capabilities

### New Capabilities
- `data-label-i18n`: Localized display of data values rendered in the web UI — a per-locale label catalog for contract types / purposes / prompt types / contexts / compare modes, a resolver with raw-value fallback, localized display titles for seeded prompt/rubric/criterion names, localized form placeholders, and client bootstrap so `app.js` can localize the compare matrix.

### Modified Capabilities
- `generation-prompts-web`: the browse / detail / form requirements now render the prompt's `contract_type`, `purpose`, `prompt_type`, and a localized display title for the prompt `name` in the active locale (raw key as fallback), with localized placeholders.
- `evaluation-rules-web`: the browse / detail / form requirements now render the rubric's `context` and localized display titles for the rubric `name` and each criterion `name` in the active locale (raw key as fallback), with localized placeholders.
- `prompt-compare-web`: the form / list / detail-matrix requirements now render `contract_type`, `mode`, `rubric_name`, and prompt names in the active locale (raw key as fallback), with localized placeholders; the matrix meta line is localized.

## Impact

- **Code**:
  - `src/web/i18n.py` (or a new `src/web/labels.py`) — add the `LABELS` catalog (zh/en) and `label_for(...)` resolver; extend `resolve_locale` / template context to expose the resolver and bootstrap `window.__LABELS__`.
  - `src/web/routes/pages.py` and `src/web/templates/base.html` — pass the label catalog / resolver into the Jinja context and bootstrap it to JS.
  - `src/web/templates/` — `prompts_list.html`, `prompt_detail.html`, `prompt_form.html`, `rubrics_list.html`, `rubric_detail.html`, `rubric_form.html`, `compare_form.html`, `compare_list.html`, `compare_detail.html`.
  - `src/web/static/app.js` — localize matrix meta and prompt/rubric labels via the bootstrapped catalog.
- **Data / DB**: none. Seed scripts (`seed_contract_prompts.py`, `seed_contract_rubrics.py`) keep their English `name` / `contract_type` / `purpose` keys; the label catalog is the source of truth for their Chinese display.
- **APIs**: no JSON API contract change (raw keys remain in API responses; localization is a presentation concern). `label_for` is additive.
- **Tests**: new tests for the label catalog (zh/en parity, fallback, display-title derivation) and template/render tests asserting Chinese labels appear and raw keys still appear as fallback for unknown values. Existing i18n parity tests (`tests/test_i18n.py`) extended to cover the new catalog.
- **Risk**: low and reversible — pure presentation layer; machine keys / joins / URLs untouched.
