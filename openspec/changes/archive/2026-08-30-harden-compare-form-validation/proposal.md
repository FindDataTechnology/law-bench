# Proposal: harden-compare-form-validation

## Why

The post-hardening critique re-run (`.impeccable/critique/2026-08-29T19-50-38Z__src-web-templates-compare-form-html.md`, 29/40) found two cheap P2 gaps on the compare launch form: nothing prevents a rubric/contract-type mismatch before a run — one wrong pick in the 80+-option select burns a full drafting+judging cycle — and the form's field labels are not programmatically associated with their inputs (only the type filter is), leaving unnamed fields for screen-reader users on the flagship flow's only door.

## What Changes

- **Rubric↔type mismatch blocks submit**: at submit time, when the selected rubric's name embeds a contract type (`contract_<type>_v<N>` pattern) that differs from the entered `contract_type`, submission is blocked with an inline localized warning naming both values. Rubrics whose names embed no type stay freely usable. This also catches the label-vs-key mistake (typing 买卖合同 instead of `sale`) by naming both sides of the mismatch.
- **Label association**: every field label in `compare_form.html` gets a `for`/`id` pair (task, contract_type, rubric, mode, n_drafts, concurrency, label) — matching the pattern already used by the type filter.
- New i18n keys for the mismatch warning (zh/en), reusing the established inline-warning grammar (visible text + tint pair, no new colors).

Non-goals: async run identity (P1, needs its own change), matrix overflow wrapper (P1), mode/concurrency collapse (P3), dashboard re-token (queued separately).

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `prompt-compare-web`: the "Compare Form Validation and Guidance" requirement gains the rubric-mismatch blocking scenario and the label-association clause.

## Impact

- `src/web/templates/compare_form.html` — for/id pairs; mismatch warning element under the rubric select.
- `src/web/static/app.js` — `initCompareForm()` submit path: prefix check + inline block before the fetch.
- `src/web/i18n.py` — one new key (`matrix.rubric_mismatch`) in zh and en.
- `src/web/static/style.css` — small inline warning style from existing tokens (fail tint + deep objection text).
- No API, service, or schema changes.
