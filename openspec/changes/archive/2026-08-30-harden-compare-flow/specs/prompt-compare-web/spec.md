# prompt-compare-web Delta — harden-compare-flow

## ADDED Requirements

### Requirement: Compare Form Validation and Guidance
The build form SHALL guide valid experiment configuration before submit: the `contract_type` field SHALL offer known contract types as suggestions (derived from contract types that exist in the prompts table, labeled via the data-label-i18n catalog) while still accepting a free-text value; the prompt checklist SHALL offer a contract-type filter and SHALL show a live selection count; the submit control SHALL be disabled with an inline visible warning whenever fewer than 2 prompts are selected; `n_drafts` SHALL be bounded [1, 8] in the UI with out-of-range values clamped before submission. Warnings SHALL be visible without submitting and SHALL use the active locale.

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
