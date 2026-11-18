## 1. i18n catalog & resolvers (`src/web/i18n.py`)

- [x] 1.1 Add a `CRITERION_I18N: dict[str, dict[str, str]]` catalog keyed by criterion `name`, each value a `{"title", "description", "guidance"}` dict, populated for the `zh` locale only. Cover every criterion `name` in `src/eval/seed/harbor/task_quality.toml` (`behavior_in_task_description`, `behavior_in_tests`, `informative_test_structure`, `anti_cheating_measures`, `structured_data_schema`, `pinned_dependencies`, `typos`, `tests_or_solution_in_image`, `test_deps_in_image`, `hardcoded_solution`, `file_reference_mentioned`) and `src/eval/seed/harbor/trial_behavior.toml` (`reward_hacking`, `task_specification`).
- [x] 1.2 Add `criterion_for(name: str, field: str, lang: str = DEFAULT, fallback: str = "") -> str`: return `CRITERION_I18N.get(name, {}).get(field)` when present for the active locale, else `fallback`. Never raises.
- [x] 1.3 Add `source_label(source: str, lang: str = DEFAULT) -> str`: `local` -> localized local label (`本地`/`local`); `harbor:vX.Y.Z` -> `Harbor v{ver}` (regex-extract version); otherwise raw `source`.
- [x] 1.4 Add chrome keys `detail.criterion_name_placeholder` and `crit_row.name_placeholder` to both `zh` (`如：party_identification`) and `en` (`e.g. party_identification`) catalogs in `LOCALES`.

## 2. Template globals (`src/web/app.py`)

- [x] 2.1 Expose `criterion_for` as a locale-bound Jinja global in `_locale_context`: `lambda name, field, fallback="": criterion_for(name, field, lang, fallback)`.
- [x] 2.2 Expose `source_label` as a locale-bound Jinja global: `lambda source: source_label(source, lang)`.

## 3. Templates

- [x] 3.1 `src/web/templates/rubric_detail.html`: render criterion title via `{{ criterion_for(c.name, 'title', c.name) }}`; render description via `{{ criterion_for(c.name, 'description', c.description) }}`; render guidance via `{{ criterion_for(c.name, 'guidance', c.guidance) }}` (apply to both the read-only display and the inline edit form's `value`/textarea defaults where appropriate).
- [x] 3.2 `rubric_detail.html`: replace the hard-coded `placeholder="e.g. party_identification"` on the add-criterion name input with `{{ t.detail.criterion_name_placeholder }}`.
- [x] 3.3 `rubric_detail.html`: render the harbor badge and the `source` `<dd>` via `{{ source_label(rubric.source) }}` instead of raw `{{ rubric.source }}`.
- [x] 3.4 `src/web/templates/rubrics_list.html`: render the harbor badge via `{{ source_label(r.source) }}` instead of raw `{{ r.source }}` (keep the `local` badge as `t.badge.local`).

## 4. Client JS (`src/web/static/app.js`)

- [x] 4.1 In `makeCriterionRow`, replace the hard-coded `placeholder="e.g. party_identification"` with `tr('crit_row.name_placeholder', 'e.g. party_identification')`.

## 5. Tests (`tests/test_i18n.py` and related)

- [x] 5.1 Add a completeness test: load every criterion `name` from the two harbor seed TOMLs and assert each has a `zh` entry in `CRITERION_I18N` (title/description/guidance present).
- [x] 5.2 Add `criterion_for` tests: zh seeded name returns localized field; unknown name / `en` locale returns the `fallback` unchanged.
- [x] 5.3 Add `source_label` tests: `local` -> `本地`(zh)/`local`(en); `harbor:v0.4.2` -> `Harbor v0.4.2`; unknown `import:foo` -> raw.
- [x] 5.4 Add/extend chrome-catalog parity test to cover the new `detail.criterion_name_placeholder` and `crit_row.name_placeholder` keys.
- [x] 5.5 Add a template-render smoke test (zh) asserting the rubric detail page shows a zh criterion description for a seeded harbor criterion and shows `如：party_identification` (not the English placeholder) and a localized source label.

## 6. Verification

- [x] 6.1 Run `uv run pytest` (or the project's test command) and confirm all i18n + web tests pass.
- [x] 6.2 Run `openspec validate add-eval-rules-cn-translate --strict` and confirm the change validates.
- [x] 6.3 Smoke-test locally: start the web app, open a harbor rubric detail page with `?lang=zh`, confirm criteria render in Chinese, the source shows `Harbor v{ver}`, and the add-criterion placeholder is Chinese; switch to `?lang=en` and confirm criteria fall back to stored English.

## 7. Contract-criteria titles & guidance tokens

- [x] 7.1 Add a `_CONTRACT_CRITERION_TITLES` zh-title catalog covering every criterion `name` in `scripts/seed_contract_rubrics.py` (206 unique names) and merge it into `CRITERION_I18N["zh"]` (title-only; description/guidance fall back to stored Chinese).
- [x] 7.2 Extend `criterion_for` to localize `PASS if` / `FAIL if` tokens in stored guidance to `通过条件：` / `不通过条件：` for `zh` when no catalog guidance entry exists; leave `en` and catalogued `zh` guidance untouched.
- [x] 7.3 Add a completeness test asserting every contract seed criterion `name` has a zh title in the catalog.
- [x] 7.4 Add a render test (zh) asserting a contract criterion heading shows the zh title and the guidance tokens are localized; assert `en` falls back to the raw name and raw `PASS if`.
- [x] 7.5 Re-run `uv run pytest` (full suite green) and re-validate the change with `openspec validate add-eval-rules-cn-translate --strict`.
- [x] 7.6 Live smoke-test `contract_sale_v1?lang=zh`: confirm all 9 criterion headings render Chinese titles and guidance shows 通过条件 / 不通过条件.
