# data-label-i18n Specification

## Purpose

Localized display of data values (machine-readable English keys) rendered in the evaluation-rules web UI. While the `web-i18n` capability localizes UI chrome (labels, headings, column headers), this capability localizes the **data values** themselves - `contract_type`, `purpose`, `prompt_type`, `context`, and compare `mode` - plus derived display titles for seeded prompt and rubric names. Machine keys remain the canonical DB / URL / join identifiers; only the rendered display is localized, with raw-key fallback for unmapped or user-authored values.
## Requirements
### Requirement: Data Label Catalog

The system SHALL maintain a per-locale data-label catalog (`LABELS`) covering five kinds: `contract_type`, `purpose`, `prompt_type`, `context`, and `mode`. The `zh` and `en` catalogs SHALL expose identical key sets for each kind. The `contract_type` catalog SHALL cover all 19 《民法典》 typical contract type keys used by the seed scripts (`sale`, `utilities_supply`, `gift`, `loan`, `guarantee`, `lease`, `financing_lease`, `factoring`, `work`, `construction`, `transport`, `technology`, `bailment`, `warehousing`, `entrustment`, `property_service`, `brokerage`, `intermediation`, `partnership`). The catalog SHALL live in `src/web/i18n.py` alongside the existing chrome `LOCALES` catalog, as a single source of truth for presentation strings.

#### Scenario: Chinese label for a known contract type

- **WHEN** the active locale is `zh` and a `contract_type` value `sale` is rendered
- **THEN** the catalog yields `买卖合同`

#### Scenario: zh/en key parity across kinds

- **WHEN** the `LABELS` catalog is loaded for `zh` and `en`
- **THEN** every kind has the same set of keys in both locales
- **AND** a parity test asserting this SHALL pass

#### Scenario: All 19 contract types are catalogued

- **WHEN** the `contract_type` kind is enumerated
- **THEN** all 19 民法典 type keys are present with a non-empty label in both `zh` and `en`

### Requirement: Label Resolution with Fallback

The system SHALL provide a `label_for(kind, value, lang)` resolver that returns the localized label for a known `(kind, value)` in the active locale. For any unmapped `value` (including user-authored free text and future keys not yet in the catalog), the resolver SHALL return the raw `value` unchanged rather than blank or raising.

#### Scenario: Known key resolves to localized label

- **WHEN** `label_for('purpose', 'drafting', 'zh')` is called
- **THEN** `起草` is returned

#### Scenario: Unknown key falls back to raw value

- **WHEN** `label_for('contract_type', 'future_crypto_loan', 'zh')` is called for a value not in the catalog
- **THEN** `future_crypto_loan` is returned unchanged

#### Scenario: User-authored Chinese name passes through

- **WHEN** `label_for` is applied to a user-authored name value `我的自定义合同`
- **THEN** `我的自定义合同` is returned unchanged

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

### Requirement: Localized Form Placeholders

The system SHALL render form input placeholder in the active locale. In `zh`, placeholders SHALL be Chinese examples (e.g. `如：买卖合同` for contract type, `如：起草` for purpose, `如：基线` for prompt type, `如：合同` for context). In `en`, placeholders SHALL be English examples. Placeholders are static example text rendered in-template, not data values.

#### Scenario: Chinese placeholder for contract type field

- **WHEN** the prompt create form is rendered in `zh`
- **THEN** the `contract_type` input placeholder is a Chinese example (e.g. `如：买卖合同`)

#### Scenario: English placeholder for contract type field

- **WHEN** the prompt create form is rendered in `en`
- **THEN** the `contract_type` input placeholder is an English example (e.g. `e.g. sale`)

### Requirement: Client Bootstrap of Data Labels

The system SHALL bootstrap the active-locale data-label catalog to the client as `window.__LABELS__` (alongside the existing `window.__LOCALE__` chrome catalog) on every page render. Client-side code (`app.js`) SHALL use `window.__LABELS__` to localize data values it renders - including the compare matrix meta line (`{ct} · {rubric} · {mode} · N={n}`), prompt labels, and rubric labels. The client SHALL degrade to the raw key if the bootstrap is absent, without throwing.

#### Scenario: Matrix meta line is localized

- **WHEN** a compare detail page renders in `zh` for a compare with `contract_type = sale`, `rubric_name = contract_sale_v1`, `gen_mode = drafter-only`
- **THEN** the meta line shows `买卖合同 · 买卖合同评价规则 · 仅起草 · N=1`

#### Scenario: Client degrades to raw key without bootstrap

- **WHEN** `window.__LABELS__` is absent (e.g. stale cached `app.js`) and the matrix meta is rendered
- **THEN** the raw keys are shown (`sale · contract_sale_v1 · drafter-only · N=1`) and no exception is raised

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

