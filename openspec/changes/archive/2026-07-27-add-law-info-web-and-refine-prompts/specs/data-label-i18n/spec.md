## ADDED Requirements

### Requirement: Law-Refined Prompt Type Label
The system SHALL include a `law-refined` entry in the `prompt_type` data-label catalog for both locales, rendering as `法律精修` in `zh` and `Law-refined` in `en`. The `zh` and `en` `prompt_type` catalogs SHALL continue to expose identical key sets (now `baseline`, `experimental`, `law-refined`). Unmapped `prompt_type` values SHALL continue to fall back to the raw value unchanged.

#### Scenario: law-refined label resolves in zh
- **WHEN** `label_for('prompt_type', 'law-refined', 'zh')` is called
- **THEN** `法律精修` is returned

#### Scenario: law-refined label resolves in en
- **WHEN** `label_for('prompt_type', 'law-refined', 'en')` is called
- **THEN** `Law-refined` is returned

#### Scenario: prompt_type parity holds with the new key
- **WHEN** the `prompt_type` kind is enumerated for `zh` and `en`
- **THEN** both locales expose `baseline`, `experimental`, and `law-refined` with non-empty labels

## MODIFIED Requirements

### Requirement: Localized Display Titles for Seeded Names
The system SHALL render a localized display title for seeded prompt and rubric names, derived from the seed naming conventions, while keeping the machine `name` as the URL path and join key. A prompt named `draft_<type_key>` SHALL display as the localized contract-type label concatenated with `起草` (e.g. `draft_sale` -> `买卖合同起草` in `zh`). A prompt named `draft_<type_key>_v<N>` SHALL display as the localized contract-type label concatenated with `起草` and the variant suffix ` v<N>` (e.g. `draft_sale_v2` -> `买卖合同起草 v2` in `zh`). A rubric named `contract_<type_key>_v<N>` SHALL display as the localized contract-type label concatenated with `评价规则` and the variant suffix ` v<N>` (e.g. `contract_sale_v1` -> `买卖合同评价规则 v1` in `zh`; `contract_sale_v2` -> `买卖合同评价规则 v2` in `zh`). Any name not matching these conventions SHALL display as the raw `name` unchanged.

#### Scenario: Seeded baseline prompt name shows a Chinese title
- **WHEN** the prompts list is rendered in `zh` for a prompt whose `name` is `draft_loan`
- **THEN** the link text shows `借款合同起草`
- **AND** the link `href` remains `/prompts/draft_loan`

#### Scenario: Seeded law-refined prompt name shows a versioned Chinese title
- **WHEN** the prompts list is rendered in `zh` for a prompt whose `name` is `draft_loan_v2`
- **THEN** the link text shows `借款合同起草 v2`
- **AND** the link `href` remains `/prompts/draft_loan_v2`

#### Scenario: Seeded v1 rubric name shows a versioned Chinese title
- **WHEN** the rubrics list is rendered in `zh` for a rubric whose `name` is `contract_lease_v1`
- **THEN** the link text shows `租赁合同评价规则 v1`
- **AND** the link `href` remains `/rubrics/contract_lease_v1`

#### Scenario: Seeded v2 rubric name shows a versioned Chinese title
- **WHEN** the rubrics list is rendered in `zh` for a rubric whose `name` is `contract_lease_v2`
- **THEN** the link text shows `租赁合同评价规则 v2`
- **AND** the link `href` remains `/rubrics/contract_lease_v2`

#### Scenario: Non-conforming name falls back to raw
- **WHEN** a user-authored prompt named `my_custom_prompt` is rendered
- **THEN** the display title is `my_custom_prompt`
