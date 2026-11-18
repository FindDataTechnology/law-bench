# Tasks: harden-compare-form-validation

## 1. i18n + template

- [x] 1.1 Add `matrix.rubric_mismatch` to zh and en catalogs: zh "规则类型 {rubric_type}（{rubric_label}）与合同类型 {ct}（{ct_label}）不一致，请修正后再运行。" / en "Rubric type {rubric_type} ({rubric_label}) does not match contract type {ct} ({ct_label}). Fix one side before running."
- [x] 1.2 `compare_form.html`: add `for`/`id` pairs to all seven field labels (task, contract_type, rubric_name, mode, n_drafts, concurrency, label); add `#compare-rubric-warning` div (hidden, `role="alert"`) under the rubric select

## 2. Validation behavior (app.js)

- [x] 2.1 In `initCompareForm()` submit path, after the min-2 guard: extract the type from the selected rubric via `^contract_([a-z0-9_]+?)_v\d+$` (case-insensitive); on mismatch with the entered `contract_type`, show the localized warning in `#compare-rubric-warning` naming both values (labels via `labelFor('contract_type', …)`), and return without sending
- [x] 2.2 Clear `#compare-rubric-warning` on any change to the rubric select or contract_type input
- [x] 2.3 Pattern-less rubric names pass through with no warning (add the case to the logic explicitly, not by accident)

## 3. Style + verification

- [x] 3.1 `style.css`: `#compare-rubric-warning` inline strip — fail tint (#fef2f2), deep objection text (var(--danger-hover)), 8px radius, small padding; no new colors, no shadow
- [x] 3.2 Re-run the web test suites (i18n/app/compare/data-labels) and the render probe pattern: assert for/id pairs present and mismatch-warning element present; `node --check app.js`
- [x] 3.3 `node .agents/skills/impeccable/scripts/detect.mjs src/web/templates` — zero new findings
- [x] 3.4 `openspec validate harden-compare-form-validation --strict`
