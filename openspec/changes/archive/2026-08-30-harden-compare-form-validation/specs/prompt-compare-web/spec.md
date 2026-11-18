# prompt-compare-web Delta — harden-compare-form-validation

## MODIFIED Requirements

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
