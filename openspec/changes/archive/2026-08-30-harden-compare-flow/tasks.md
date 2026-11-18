# Tasks: harden-compare-flow

## 1. Route context + template scaffolding

- [x] 1.1 Pass `contract_types` (distinct contract types from the prompts table, with localized labels resolvable via the labels catalog) into the `/compare/new` page context
- [x] 1.2 `compare_form.html`: convert `contract_type` to `<input list="contract-type-options">` + `<datalist>` of localized suggestions; move the hardcoded task/label placeholders into i18n keys (`t.form.task_ph`, `t.form.label_ph`)
- [x] 1.3 `compare_form.html`: wrap the prompt checklist in `fieldset`/`legend` (visual parity via a small legend rule in style.css); add the filter select (全部类型 + distinct types) above the checklist and a `#compare-count` span beside the prompts label
- [x] 1.4 `compare_form.html`: localize the `mode` option label (`仅起草` / localized equivalent via the labels catalog); add `max="8"` to `n_drafts`; add the cancel button (hidden until running) beside Run Compare

## 2. i18n catalog

- [x] 2.1 Add zh/en keys: selection counter (`已选 {k} 个（至少 2）`), filter label, cancel-run, elapsed prefix (`已运行 {t}`), run-cancelled note (config preserved; server may still be running), duplicate-resubmit confirm, fail-count warning — in both locales with parity
- [x] 2.2 Run the existing i18n parity check/tests covering the new keys

## 3. Form behavior (app.js `initCompareForm`)

- [x] 3.1 Live counter: update `#compare-count` on every checklist change; disable submit + show inline warning below 2 selections; enable at ≥2 (count text is the label, not color alone)
- [x] 3.2 Checklist filter: show/hide `.check` rows by `data-contract-type` without touching checked state; clearing the filter restores all rows
- [x] 3.3 Rubric ordering: when `contract_type` matches `contract_<type>_v…` rubric names, float those options to the top (no filtering, no blocking)
- [x] 3.4 Clamp `n_drafts` into [1, 8] on change and before submit (reflect the clamped value in the field)
- [x] 3.5 Run instrumentation: elapsed timer (`setInterval` → `已运行 m:ss`), cancel button shown while running, `AbortController` on the fetch; abort/error path re-enables the form, clears the timer, and shows the localized "waiting cancelled / config preserved" note
- [x] 3.6 Duplicate-resubmit guard: store the submitted body hash in `sessionStorage` on error/abort; on an identical resubmit require an inline localized confirmation before firing; changed config bypasses the gate

## 4. Matrix accessibility (app.js compare-detail render + style.css)

- [x] 4.1 Render each verdict cell as a `<button class="cell-btn">` inside the `<td>` (tint background/text on the button, existing padding); `:focus-visible` = 2px `bench-blue` outline, no shadow
- [x] 4.2 Keyboard + focus management: cells open reasoning on Enter/Space; `#compare-reasoning`/`#compare-draft` close on Escape and return focus to the opener (track opener at open time)
- [x] 4.3 `role="status"`/`aria-live="polite"` on `#compare-status` and `#compare-meta`; matrix `<caption>` (visually hidden or styled small/muted)
- [x] 4.4 Contrast: fail-cell text token swap `objection-red → objection-red-deep` in style.css; matrix header `th` text → `ledger-ink`; verify both ≥ 4.5:1 against their backgrounds

## 5. Verification

- [x] 5.1 Update/extend tests: form validation unit-ish checks where the existing web tests exercise the form (or add minimal DOM tests following existing patterns in `tests/`); update any `fd-coding-law-bench-mcp` test asserting on `td.cell` markup
- [x] 5.2 Run the full test suite (`pytest`) and `openspec validate harden-compare-flow --strict`
- [x] 5.3 Run `node .agents/skills/impeccable/scripts/detect.mjs src/web/templates` — zero new findings; confirm no colors outside DESIGN.md entered
- [x] 5.4 Run the `$impeccable audit` accessibility pass over the compare surface; fold any new P1 findings into fixes before closing
- [ ] 5.5 Manual pass in the running app (when the dev venv is repaired): keyboard-only walk of launch → run (cancel) → matrix inspect; zh/en copy spot-check
  - Status: venv repaired (rebuilt without the crewai/litellm chain; litellm v1.93.0 fails to build on Windows). Server-side render probe passed 14/14 markup checks on `/compare/new` + `/compare/{id}` (datalist, fieldset, filter, counter, aria-live, localized mode option, cancel button); zh/en parity covered by tests. The interactive browser walk remains blocked: the app fails closed at startup when the Logto IdP is unreachable, and the remote dev infra (IdP + original DB tunnel) is down from this machine. Run the walk when the tunnel is back.
- [x] 5.6 Update DESIGN.md's fail-cell line to name `objection-red-deep` as the fail-text token (one-word alignment, at archive or now)
