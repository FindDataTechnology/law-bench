# ADDED Spec: contract-samples-web

## Purpose

Web UI for browsing the full corpus of stored contract artifacts (724 content-addressed samples across 66 contract types) with type→scenario→stance cascading filters, paginated metadata table, and direct DOCX/PDF download. This is a browse-and-download layer over the `contract-artifact-storage` capability — no slot filling, no generation triggers.

## ADDED Requirements

### Requirement: Samples Library Page

The system SHALL expose `GET /samples` returning server-rendered HTML (Jinja2, `include_in_schema=False`, route name `page_samples`) that displays all stored `contract_artifacts` rows in a paginated metadata table, newest first. The page SHALL accept query parameters `contract_type` (optional), `scenario` (optional), `stance` (optional), `limit` (1–100, default 50), and `offset` (≥0, default 0), and SHALL render a filter form, the data table, and pagination controls. The page SHALL function with zero client-side JavaScript for core navigation (filters and pagination are plain GET form submissions / anchor links).

#### Scenario: Page renders with no filters

- **WHEN** a client requests `GET /samples` with no query parameters
- **THEN** the response is HTML (200) containing a `<table>` with up to 50 rows of artifact metadata, a type `<select>` listing all contract classes, and pagination controls reflecting the unfiltered total

#### Scenario: Pagination controls are anchor links

- **WHEN** the page is rendered with `total > limit`
- **THEN** the "next" control is an `<a href>` carrying all current filter params plus `offset = current + limit`, and the "previous" control (when `offset > 0`) carries `offset = current - limit`; no JavaScript is required to navigate

#### Scenario: Route is excluded from OpenAPI schema

- **WHEN** `GET /openapi.json` is fetched
- **THEN** the path `/samples` is absent (the route is declared `include_in_schema=False`)

### Requirement: Cascading Filter Dropdowns

The page SHALL present three `<select>` filters in cascade: contract type (always populated), scenario (populated only after a contract type is selected), and stance (populated only after a contract type is selected). All three SHALL auto-submit the form on change (`onchange="this.form.submit()"`) and SHALL include a `<noscript>` submit button for non-JS clients. The "全部" (no-filter) option SHALL be the first option in each select. The scenario and stance options SHALL be the distinct non-null values present in `contract_artifacts` rows for the selected contract type.

#### Scenario: Selecting a type populates scenario and stance options

- **WHEN** the user selects `sale` in the type dropdown and the form submits
- **THEN** the re-rendered page's scenario `<select>` contains the distinct non-null `scenario` values from all sale artifacts, the stance `<select>` contains the distinct non-null `stance` values, and both have "全部" as their first option

#### Scenario: Scenario select is empty without a type

- **WHEN** the page is rendered with no `contract_type` selected
- **THEN** the scenario and stance `<select>`s contain only the "全部" option

#### Scenario: Filter is retained across submission

- **WHEN** the user selects type `sale` and scenario `农产品买卖`, then changes the stance dropdown
- **THEN** the re-rendered page preserves the selected type and scenario in their respective dropdowns (selected attributes set)

### Requirement: Scenario and Stance Filter Semantics

The `scenario` query parameter, when present and non-empty, SHALL filter rows to `contract_artifacts` whose `scenario` column equals that value (excluding base rows with NULL scenario). When absent or empty ("全部"), it SHALL apply no scenario filter (including base rows with NULL scenario). The `stance` parameter SHALL follow the same two-state semantics against the `stance` column. Both filters SHALL compose with each other and with the `contract_type` filter via AND logic. A `contract_type` that has no artifacts SHALL render an empty table (no 500 error).

#### Scenario: Specific scenario excludes base rows

- **WHEN** `GET /samples?contract_type=sale&scenario=农产品买卖` is requested
- **THEN** every row in the table has `scenario == "农产品买卖"`; no NULL-scenario (base) rows appear

#### Scenario: No scenario filter includes base rows

- **WHEN** `GET /samples?contract_type=sale` is requested (no scenario param)
- **THEN** the table includes both scenario-tagged rows and NULL-scenario (base) rows for sale

#### Scenario: Unknown type renders empty table

- **WHEN** `GET /samples?contract_type=does_not_exist` is requested
- **THEN** the response is 200 with an empty `<tbody>` and the scenario/stance selects containing only "全部" (no crash, no 500)

### Requirement: Server-Side Pagination

The page SHALL paginate artifact rows server-side via `LIMIT`/`OFFSET`. The total count returned alongside the rows SHALL reflect the *filtered* set (i.e., with all active filters applied), not the unfiltered table. The page-info span SHALL display current page / total pages and the filtered total count. `offset` values beyond the filtered total SHALL yield an empty row list with the unchanged filtered total.

#### Scenario: Filtered total drives page count

- **WHEN** `GET /samples?contract_type=sale` is requested and sale has 88 artifacts with default `limit=50`
- **THEN** the page-info shows 2 total pages and a total of 88, and the table has 50 rows

#### Scenario: Offset beyond total yields empty rows

- **WHEN** `GET /samples?contract_type=sale&offset=10000` is requested
- **THEN** the table has zero rows, the filtered total is unchanged, and `has_next` is false

### Requirement: Download Links Per Artifact

Each artifact row in the samples table SHALL present two download anchors: one linking to the existing `GET /api/contracts/artifacts/{id}/download?format=docx` endpoint and one to `?format=pdf`. The links SHALL be plain `<a href>` elements (no JS), so the browser triggers a streaming download directly. A format not stored for that artifact (NULL key) SHALL render a disabled (greyed) link rather than a clickable one.

#### Scenario: DOCX and PDF download anchors render

- **WHEN** an artifact row with both `docx_key` and `pdf_key` non-null is rendered
- **THEN** the row contains an `<a href>` ending in `/download?format=docx` and another ending in `/download?format=pdf`

#### Scenario: Missing format renders disabled link

- **WHEN** an artifact row with `pdf_key` NULL is rendered
- **THEN** the PDF download control is disabled (not an actionable link), while the DOCX control remains a normal link

### Requirement: Samples Service Layer

The system SHALL add three read-only query functions to `src/contracts/artifacts.py` that do not modify any existing function: `distinct_scenarios(contract_type, db=None) -> list[str]` returning distinct non-null `scenario` values for a type (ordered); `distinct_stances(contract_type, db=None) -> list[str]` returning distinct non-null `stance` values; and `list_samples(contract_type=None, scenario=None, stance=None, limit=50, offset=0, db=None) -> tuple[list[dict], int]` returning metadata rows (excluding `body_text`) plus the filtered total count. All three SHALL use parameterized queries (no string interpolation of user input). The existing `list_artifacts`, `get_artifact`, and `download` functions SHALL remain unchanged (backward compatible).

#### Scenario: distinct_scenarios returns non-null set

- **WHEN** `distinct_scenarios('sale')` is called after sale artifacts are stored
- **THEN** it returns a list of non-empty scenario strings (no None/NULL entries), ordered

#### Scenario: list_samples excludes body_text

- **WHEN** `list_samples(contract_type='sale', limit=5)` is called
- **THEN** the returned row dicts have no `body_text` key, and the second tuple element equals the filtered count of sale artifacts

#### Scenario: list_samples filters compose via AND

- **WHEN** `list_samples(contract_type='sale', scenario='农产品买卖', stance='pro_a')` is called
- **THEN** every returned row has both `scenario == '农产品买卖'` and `stance == 'pro_a'`

#### Scenario: Existing list_artifacts is unchanged

- **WHEN** `list_artifacts(contract_type='sale')` is called after the change
- **THEN** its signature, return shape, and behavior are identical to before (no regression)

### Requirement: Nav and App Wiring

The system SHALL register the `samples` router in `src/web/app.py` (`app.include_router(samples.router)`) and SHALL add a "合同样本" navigation link to `src/web/templates/base.html` pointing at `url_for('page_samples')`. The samples page SHALL inherit `base.html` so the locale context processor and shared nav apply.

#### Scenario: Nav link appears on all pages

- **WHEN** any page extending `base.html` is rendered
- **THEN** the nav contains a "合同样本" anchor whose `href` resolves to `/samples`

#### Scenario: Router is included in the app

- **WHEN** the FastAPI app is constructed
- **THEN** the `/samples` route is registered and reachable at runtime
