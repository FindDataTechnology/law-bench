# Implementation Tasks

## 1. Data-label catalog & resolver (`src/web/i18n.py`)

- [x] 1.1 Add a `LABELS` dict to `src/web/i18n.py` with `zh` and `en` sub-dicts, each containing the five kinds: `contract_type`, `purpose`, `prompt_type`, `context`, `mode`.
- [x] 1.2 Populate `contract_type` with all 19 民法典 type keys (`sale`->买卖合同/Sale, `utilities_supply`->供用电水气热力合同, `gift`->赠与合同, `loan`->借款合同, `guarantee`->保证合同, `lease`->租赁合同, `financing_lease`->融资租赁合同, `factoring`->保理合同, `work`->承揽合同, `construction`->建设工程合同, `transport`->运输合同, `technology`->技术合同, `bailment`->保管合同, `warehousing`->仓储合同, `entrustment`->委托合同, `property_service`->物业服务合同, `brokerage`->行纪合同, `intermediation`->中介合同, `partnership`->合伙合同); cross-check the keys against `scripts/seed_contract_prompts.py` and `chinese_contracts_class.md`.
- [x] 1.3 Populate `purpose` (`drafting`->起草/Drafting), `prompt_type` (`baseline`->基线/Baseline, `experimental`->实验/Experimental, `improved`->改进/Improved), `context` (`contract`->合同/Contract), `mode` (`drafter-only`->仅起草/Drafter-only).
- [x] 1.4 Implement `label_for(kind: str, value: str, lang: str = DEFAULT) -> str` that walks `LABELS[lang][kind]` and returns the mapped label, or the raw `value` unchanged if `kind` or `value` is unmapped (never raises, never blanks).
- [x] 1.5 Add a parity helper/assertion path so `zh` and `en` expose identical key sets per kind (mirrors the existing chrome-catalog parity check).

## 2. Display-title derivation (`src/web/i18n.py`)

- [x] 2.1 Implement `title_for_prompt(name: str, lang: str = DEFAULT) -> str`: if `name` matches `draft_<type_key>`, return `label_for('contract_type', type_key, lang) + ('起草' if zh else ' Drafting')`; else return `name` unchanged.
- [x] 2.2 Implement `title_for_rubric(name: str, lang: str = DEFAULT) -> str`: if `name` matches `contract_<type_key>_v<N>`, return `label_for('contract_type', type_key, lang) + ('评价规则' if zh else ' Rubric')`; else return `name` unchanged.
- [x] 2.3 Verify both helpers fall back to the raw `name` for non-conforming (user-authored) names, including names already in Chinese.

## 3. Template context & client bootstrap (`src/web/app.py`, `src/web/templates/base.html`)

- [x] 3.1 Extend `_locale_context` in `src/web/app.py` to inject `labels` (active-locale `LABELS`), `labels_json` (`json.dumps(labels, ensure_ascii=False)`), and `label_for` (a callable bound to the active `lang`) plus `title_for_prompt`/`title_for_rubric` bound to the active `lang`.
- [x] 3.2 In `src/web/templates/base.html`, add `window.__LABELS__ = {{ labels_json|safe }};` alongside the existing `window.__LOCALE__` bootstrap.
- [x] 3.3 Register `label_for`, `title_for_prompt`, `title_for_rubric` as Jinja globals (or pass via context) so templates can call them directly.

## 4. Prompt templates (`src/web/templates/`)

- [x] 4.1 `prompts_list.html`: render `p.name` via `title_for_prompt(p.name)` as the link text; render `p.contract_type` and `p.purpose` via `label_for(...)`; render `p.prompt_type` badge via `label_for('prompt_type', p.prompt_type)` (keep raw fallback). Keep link `href` on the machine `name`.
- [x] 4.2 `prompt_detail.html`: render the heading via `title_for_prompt(prompt.name)`; render `contract_type`/`purpose` via `label_for(...)`; render the `prompt_type` badge via `label_for('prompt_type', ...)`. Keep machine name available (e.g. in `<code>` or as the URL).
- [x] 4.3 `prompt_form.html`: localize placeholders - `name` (`如：买卖合同起草` / `e.g. 买卖合同起草`), `contract_type` (`如：买卖合同` / `e.g. sale`), `purpose` (`如：起草` / `e.g. drafting`), `prompt_type` (`如：基线` / `e.g. baseline`). Keep the input `value` as the raw machine value (no change to stored data).

## 5. Rubric templates (`src/web/templates/`)

- [x] 5.1 `rubrics_list.html`: render `r.name` via `title_for_rubric(r.name)` as link text; render `r.context` via `label_for('context', r.context)`. Keep link `href` on the machine `name`.
- [x] 5.2 `rubric_detail.html`: render the heading via `title_for_rubric(rubric.name)`; render `rubric.context` via `label_for('context', ...)`. Leave criterion `name` rendering as-is (raw) per Non-Goal.
- [x] 5.3 `rubric_form.html`: localize placeholders - `name` (`如：买卖合同评价规则` / `e.g. contract_sale_v2`), `context` (`如：合同` / `e.g. contract`). Keep input `value` raw.

## 6. Compare templates (`src/web/templates/`)

- [x] 6.1 `compare_form.html`: localize `contract_type` placeholder (`如：买卖合同`); render the rubric `<select>` option labels via `title_for_rubric(r.name)`; render prompt-pick checkbox labels via `title_for_prompt(p.name)` and `label_for('contract_type', p.contract_type)`. Keep form field `value`s as raw machine keys.
- [x] 6.2 `compare_list.html`: render `c.contract_type` via `label_for('contract_type', ...)`; render `c.rubric_name` via `title_for_rubric(...)`; render `c.gen_mode` via `label_for('mode', ...)`. Keep link `href` on the numeric `c.id`.
- [x] 6.3 `compare_detail.html`: no static data to localize (matrix is client-rendered), but confirm the page title/heading still render correctly with the localized matrix.

## 7. Client localization (`src/web/static/app.js`)

- [x] 7.1 Add a `labelFor(kind, value)` JS helper that reads `window.__LABELS__` and returns the mapped label or the raw `value` (mirrors the Python resolver).
- [x] 7.2 Add `titleForPrompt(name)` / `titleForRubric(name)` JS helpers mirroring the Python derivation, reading `window.__LABELS__`.
- [x] 7.3 Localize the matrix meta line (`{ct} · {rubric} · {mode} · N={n}`) in `renderMeta`/`fmt(tr('matrix.meta', ...), ...)` to use `labelFor('contract_type', ct)`, `titleForRubric(rubric)`, `labelFor('mode', mode)`.
- [x] 7.4 Localize prompt column headers (use `labelFor('prompt_type', ptype)` -> `titleForPrompt(name)` -> raw `name` fallback chain).
- [x] 7.5 Ensure graceful degradation: if `window.__LABELS__` is absent, fall back to raw keys without throwing (mirror the existing chrome-catalog guard).

## 8. Tests (`tests/`)

- [x] 8.1 Extend `tests/test_i18n.py` (or add `tests/test_data_labels.py`) to assert: zh/en key parity for every `LABELS` kind; all 19 `contract_type` keys present in both locales; `label_for` returns the right label for known keys and the raw value for unknown keys; `title_for_prompt`/`title_for_rubric` produce the expected Chinese titles for seeded names and fall back to raw for non-conforming names.
- [x] 8.2 Add template/render tests (extend the existing web test suite) asserting: the prompts list in `zh` shows `买卖合同` / `起草` / `买卖合同起草` for a `draft_sale` prompt; the rubrics list in `zh` shows `买卖合同评价规则` for `contract_sale_v1`; the compare list in `zh` shows `买卖合同` and `仅起草`; unknown values fall back to the raw key.
- [x] 8.3 Add a client-side test (or JS unit test) asserting the matrix meta line is localized when `window.__LABELS__` is present and falls back to raw keys when absent.
- [x] 8.4 Run the full suite (`uv run pytest`) and confirm no regressions in existing i18n / web / compare tests.

## 9. Verification

- [x] 9.1 Re-seed (`uv run python scripts/seed_contract_prompts.py` and `seed_contract_rubrics.py`) and manually open `/prompts`, `/prompts/draft_sale`, `/rubrics`, `/rubrics/contract_sale_v1`, `/compare`, `/compare/new`, and a compare detail in `zh` - confirm 合同类型 / 用途 / 名称 render in Chinese and links still resolve.
- [x] 9.2 Toggle to `en` (`?lang=en`) and confirm English labels render (e.g. `Sale` / `Drafting` / `Sale Drafting`).
- [x] 9.3 Create a user-authored prompt/rubric with a non-conforming name and confirm the raw name is shown (no blank, no crash).
- [x] 9.4 Confirm the JSON API (`/api/prompts`, `/api/rubrics`, `/api/compare`) still returns raw machine keys (unaffected).
