# prompt-compare-web Specification

## Purpose
Expose prompt comparison over a JSON API and a web UI with form validation, localStorage state mirroring, accessibility, and run instrumentation.

## Requirements
### Requirement: Compare JSON API
The system SHALL provide a JSON API under `/api/compare` in the existing FastAPI app: `POST /api/compare` to create and run a compare (body: contract_type, rubric_name, task_desc, prompt names, mode, n_drafts, and an optional integer `concurrency` bounding parallel draft generation, clamped to [1, 8] with default 1), `GET /api/compare` to list recent compares, `GET /api/compare/{id}` to fetch the full grouped result, and `GET /api/compare/{id}/run/{run_id}/draft` to lazy-fetch a single run's `draft_text`. Each handler SHALL take the standard `db` dependency so tests can point it at a throwaway DB. The `concurrency` field SHALL be additive: requests without it behave exactly as before.

#### Scenario: Create and run a compare via API
- **WHEN** `POST /api/compare` is called with a valid area, prompt set, mode, and n_drafts
- **THEN** the compare runs synchronously (or async with a job id - see Open Questions) and returns the grouped result with a `compare_id`
- **AND** `GET /api/compare/{id}` returns the same grouped result thereafter

#### Scenario: Create with a concurrency override
- **WHEN** `POST /api/compare` is called with `concurrency: 4` for 3 prompts × 2 drafts
- **THEN** the compare runs with at most 4 drafts generated simultaneously and the grouped result is identical in content and row order to a concurrency-1 run of the same inputs

#### Scenario: Concurrency outside the range is clamped
- **WHEN** `POST /api/compare` is called with `concurrency: 99`
- **THEN** the compare runs with effective concurrency 8 and succeeds

#### Scenario: Lazy-fetch a draft
- **WHEN** `GET /api/compare/7/run/42/draft` is called
- **THEN** the `draft_text` for run 42 is returned
- **AND** `draft_text` is NOT included in the default `GET /api/compare/{id}` payload (kept compact)

#### Scenario: API delegates to the service layer
- **WHEN** any compare endpoint runs
- **THEN** it delegates to `src/eval/compare.py` and maps service errors to HTTP statuses via the existing `app.py` handlers

### Requirement: Compare Web UI
The system SHALL provide HTML pages (`/compare` list, `/compare/new` build-and-run, `/compare/{id}` result) mirroring the existing rubric/prompt UI pattern, with a `Compare` nav link in `base.html`. The build form SHALL render its `contract_type` field, `rubric` select option labels, and prompt-pick checkbox labels (prompt name and contract_type) with localized labels and localized placeholders per `data-label-i18n` (raw-key fallback for unmapped or user-authored values). The build form SHALL also render a `concurrency` number input (default 1, min 1, max 8) with a localized label (zh: 并发), submitted with the compare body. The list SHALL render `contract_type`, `rubric_name`, and `mode` as localized labels in the active locale (raw-key fallback). The result page SHALL render a per-criterion matrix: rows = rubric criteria, columns = prompts (header = the localized `prompt_type` label, falling back to the prompt's localized display title per `data-label-i18n`, then the raw prompt `name`), cell = verdict (n_drafts = 1) or `k/N` pass-rate (n_drafts > 1). The result meta line (`{ct} · {rubric} · {mode} · N={n}`) SHALL be localized in the active locale via the client-bootstrapped data-label catalog (`window.__LABELS__`). Each cell SHALL be expandable to show the judge reasoning; each column SHALL offer a "view draft" action that lazy-loads `draft_text`. Run-level `n_passed`/`n_criteria` and mean pass-rate SHALL be shown as secondary headlines.

#### Scenario: Build and run a compare in the browser
- **WHEN** the user selects an area (contract_type, rubric, task), picks ≥2 prompts, sets mode and n_drafts, and submits
- **THEN** the compare runs and the result page renders the criteria × prompts matrix

#### Scenario: Build form exposes draft concurrency
- **WHEN** the user opens `/compare/new`
- **THEN** the form shows a number input labeled 并发 (zh locale; localized label otherwise) with default 1, minimum 1, maximum 8
- **AND** its value is sent as the `concurrency` field of the compare creation body

#### Scenario: The matrix uses localized prompt_type as column headers
- **WHEN** a compare result is rendered for prompts with `prompt_type` set, in locale `zh`
- **THEN** each column header shows the localized label for the prompt's `prompt_type` (e.g. `baseline` -> `基线`)
- **AND** a blank `prompt_type` falls back to the prompt's localized display title, then to the raw prompt `name`

#### Scenario: Inspect a cell and a draft
- **WHEN** the user clicks a matrix cell
- **THEN** the judge reasoning for that criterion/prompt is revealed
- **AND** when the user clicks "view draft" for a column, the `draft_text` is lazy-fetched and shown

#### Scenario: The result meta line is localized
- **WHEN** a compare detail page renders in `zh` for a compare with `contract_type = sale`, `rubric_name = contract_sale_v1`, `gen_mode = drafter-only`, `n_drafts = 1`
- **THEN** the meta line shows `买卖合同 · 买卖合同评价规则 · 仅起草 · N=1`

#### Scenario: The compare list shows localized labels
- **WHEN** a user views `/compare` with locale `zh` for a compare with `contract_type = sale` and `gen_mode = drafter-only`
- **THEN** the contract_type cell shows `买卖合同` and the mode cell shows `仅起草`

#### Scenario: The build form uses localized placeholders
- **WHEN** the user opens `/compare/new` with locale `zh`
- **THEN** the `contract_type` input placeholder is a Chinese example (e.g. `如：买卖合同`)
- **AND** prompt-pick checkboxes show the prompt's localized display title and contract_type label
### Requirement: localStorage Mirror of Compare State
The compare web UI SHALL persist state to browser `localStorage` in two layers: (1) WIP form state - selected prompt names, task, rubric, mode, and n_drafts - saved on every change and restored on page load so a refresh does not lose an in-progress config; (2) a compact results mirror per compare - the matrix (prompt_type headers, criterion titles, verdicts/pass-rates) and judge reasoning - saved under a byte-budget LRU cap (~4 MB, evicting the oldest compares first) and a versioned cache key. `draft_text` SHALL NOT be mirrored. On load, the UI SHALL paint from `localStorage` instantly then reconcile with the server, with the DB as source of truth (DB wins on conflict; a deleted compare is dropped from the cache).

#### Scenario: WIP form state survives refresh
- **WHEN** the user partially configures a compare (selects prompts, types a task) and refreshes the page
- **THEN** the form is restored to its pre-refresh state from `localStorage`

#### Scenario: Results are mirrored for instant review
- **WHEN** a compare completes
- **THEN** its compact matrix + reasoning is written to `localStorage`
- **AND** re-opening `/compare/{id}` paints from `localStorage` before the server responds
- **AND** `draft_text` is not present in the mirrored entry

#### Scenario: Byte-budget eviction keeps the cache under quota
- **WHEN** a `localStorage` write would exceed the ~4 MB budget
- **THEN** the oldest mirrored compares are evicted (LRU) until the write fits
- **AND** the current compare's entry is never partially written

#### Scenario: Stale cache is invalidated by version
- **WHEN** the result shape changes (cache key version bump) and the page loads
- **THEN** the old-version cache entries are discarded, not served

#### Scenario: DB wins on conflict
- **WHEN** the server's compare row is newer than the cached mirror, or the compare was deleted on the server
- **THEN** the UI overwrites the cache from the DB (or drops the entry if deleted) and renders the DB state

### Requirement: Compare Form Validation and Guidance
The build form SHALL guide valid experiment configuration before submit: the `contract_type` field SHALL offer known contract types as suggestions (derived from contract types that exist in the prompts table, labeled via the data-label-i18n catalog) while still accepting a free-text value; the prompt checklist SHALL offer a contract-type filter and SHALL show a live selection count; the submit control SHALL be disabled with an inline visible warning whenever fewer than 2 prompts are selected; `n_drafts` SHALL be bounded [1, 8] in the UI with out-of-range values clamped before submission. The form SHALL prevent rubric/contract-type mismatches before a run: when the selected rubric's name embeds a contract type (the `contract_<type>_v<N>` naming convention) that differs from the entered `contract_type`, submission SHALL be blocked with an inline localized warning naming both values; rubrics whose names embed no type remain freely usable. Every field label on the form SHALL be programmatically associated with its input (`for`/`id` pairing). Warnings SHALL be visible without submitting and SHALL use the active locale.

#### Scenario: contract_type offers catalog suggestions
- **WHEN** the user focuses the `contract_type` field on `/compare/new` and prompts exist for types `sale` and `lease`
- **THEN** the field suggests the localized labels for those types (e.g. 买卖合同, 租赁合同)
- **AND** the user can still type and submit a value not in the suggestion list

#### Scenario: checklist filters by contract type
- **WHEN** the user sets the checklist filter to a contract type
- **THEN** only prompts of that type remain visible and selectable
- **AND** changing or clearing the filter restores the hidden prompts without losing their checked state

#### Scenario: live count and submit guard
- **WHEN** fewer than 2 prompts are checked
- **THEN** a live count in the active locale is shown (e.g. 已选 1 个（至少 2）) and the submit control is disabled
- **AND** when the count reaches 2 the submit control enables without a page reload

#### Scenario: n_drafts is bounded in the UI
- **WHEN** the user enters `n_drafts` as 0 or 99
- **THEN** the submitted value is clamped into [1, 8] and the field reflects the clamped value

#### Scenario: rubric/type mismatch blocks submit
- **WHEN** the user selects rubric `contract_lease_v1` while `contract_type` is `sale` and submits
- **THEN** submission is blocked and an inline localized warning names both the rubric's embedded type (lease/租赁合同) and the entered type (sale/买卖合同)
- **AND** no request is sent until the mismatch is resolved

#### Scenario: type-free rubrics are never blocked
- **WHEN** the user selects a rubric whose name embeds no contract type (any naming pattern other than `contract_<type>_v<N>`)
- **THEN** submission proceeds regardless of the entered contract_type

#### Scenario: every field label is associated
- **WHEN** a screen reader or label click targets any field on `/compare/new` (task, contract type, rubric, mode, drafts, concurrency, label)
- **THEN** the label is programmatically associated with its input (`for`/`id`), so the field announces its name and clicking the label focuses the input

### Requirement: Compare Run Instrumentation
While a compare run is in flight after submit, the UI SHALL show an elapsed-time indicator that updates without page reload, SHALL keep the active-locale status message visible, SHALL offer a cancel control that aborts the client's wait for the response and returns the form to an editable state, and SHALL confirm that the form configuration was preserved. After a failed or cancelled run, a resubmission of an identical configuration SHALL require explicit confirmation before starting, to prevent accidental duplicate runs. Aborting the client wait SHALL NOT claim to stop server-side work.

#### Scenario: elapsed time is visible during the run
- **WHEN** a compare run is in flight
- **THEN** the status area shows an updating elapsed-time indicator (e.g. 已运行 0:42) alongside the localized running message

#### Scenario: cancel returns the form to editable state
- **WHEN** the user activates the cancel control during a run
- **THEN** the client stops waiting for the response, the submit control re-enables, and a localized note confirms the configuration is preserved
- **AND** the status area does not imply the server-side run was stopped

#### Scenario: duplicate resubmission requires confirmation
- **WHEN** a previous submit failed or was cancelled and the user submits the identical configuration again
- **THEN** the UI asks for explicit confirmation before starting the run
- **AND** a changed configuration submits without the extra confirmation

### Requirement: Compare Matrix Accessibility
The compare result SHALL be operable by keyboard and readable by assistive technology: each verdict cell SHALL be a keyboard-focusable control that opens the judge reasoning on activation (Enter/Space) and preserves the tint-pair visual grammar; the reasoning and draft panels SHALL close on Escape and SHALL return focus to the control that opened them; run status and result meta changes SHALL be announced via an ARIA live region; the prompt checklist on the build form SHALL be a labeled group (fieldset/legend or equivalent); verdict text SHALL meet WCAG AA contrast (4.5:1) against its tint background.

#### Scenario: keyboard-only cell inspection
- **WHEN** a keyboard user tabs to a verdict cell and presses Enter or Space
- **THEN** the judge reasoning panel opens
- **AND** pressing Escape closes it and focus returns to the same cell

#### Scenario: status changes are announced
- **WHEN** the run status text changes (running, error, complete) or the result meta renders
- **THEN** the change is announced by an ARIA live region

#### Scenario: verdict text meets AA contrast
- **WHEN** a fail verdict renders (text on its fail-tint background)
- **THEN** the text meets WCAG AA contrast (≥ 4.5:1) using the darker objection token, without introducing a color outside the committed palette

#### Scenario: prompt checklist is a labeled group
- **WHEN** a screen reader encounters the prompt checklist on `/compare/new`
- **THEN** it is announced as a group with an accessible name (the prompts label)

### Requirement: Matrix Horizontal Overflow Behavior
The verdict matrix SHALL remain fully readable when its columns exceed the panel width: the matrix SHALL scroll horizontally within a container inside its panel rather than overflowing or clipping, the table SHALL carry a minimum width so narrow results do not collapse columns illegibly, and the header's raw prompt-name subline SHALL be allowed to wrap while the localized display title and verdict cells keep single-line rendering. No content SHALL be clipped without a scroll path to it.

#### Scenario: many columns scroll instead of breaking layout
- **WHEN** a compare result renders with enough prompts that the matrix exceeds the 980px panel width
- **THEN** the matrix scrolls horizontally inside its container and the page layout does not break

#### Scenario: narrow matrices stay legible
- **WHEN** a compare result has few prompts
- **THEN** the table retains a minimum width that keeps criterion labels and verdict cells legible

#### Scenario: long prompt names wrap in the header subline
- **WHEN** a column header's raw prompt name is longer than its column
- **THEN** the muted prompt-name subline wraps while the localized display title above it stays on one line
