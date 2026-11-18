## ADDED Requirements

### Requirement: Contract Template Slot Audit
The system SHALL provide a deterministic slot-coverage evaluator over contract 母版 that takes no LLM and no database. `audit_template(contract_type)` SHALL load the template via `src.contracts.templates.get_template` and, for every slot in `src.contracts.slots.REQUIRED_SLOTS`, classify it as `present` (the `{{slot}}` token appears in the body **before** the `## 签署信息` heading), `tail_only` (the token appears **only** at or after the `## 签署信息` heading), or `missing` (the token does not appear in the body at all). It SHALL additionally report `extra_slots` (slot names found in the body that have no entry in the template's `slot_instructions`) and `orphan_instructions` (`slot_instructions` entries whose `name` is absent from the body). It SHALL return a per-template result with `status` (`pass` or `fail`), a `coverage` ratio of present body-proper required slots over total body-proper required slots, and the five classification lists. Slot tokens SHALL be matched with `src.docs.SLOT_PATTERN`; `REQUIRED_SLOTS` and `default_slot_instructions` SHALL be imported, not redefined. `audit_body(body, slot_instructions)` SHALL expose the same classification for an arbitrary body string so the evaluator can be reused outside the registry.

#### Scenario: All required slots present in the body proper
- **WHEN** `audit_template("sale")` is called for a template whose body contains every `REQUIRED_SLOTS` token before the `## 签署信息` heading
- **THEN** the result `status` is `pass`, every required slot is listed in `present`, and `missing`, `tail_only`, `extra_slots`, and `orphan_instructions` are all empty

#### Scenario: A required party slot is entirely missing
- **WHEN** a template body omits the `{{party_b}}` token entirely
- **THEN** `party_b` is listed in `missing`, the result `status` is `fail`, and `coverage` is less than `1.0`

#### Scenario: A body-proper slot appears only in the 签署信息 tail
- **WHEN** a template body contains `{{party_a}}` only at or after the `## 签署信息` heading and not before it
- **THEN** `party_a` is listed in `tail_only` and the result `status` is `fail`

#### Scenario: Unknown slot in the body is flagged as extra
- **WHEN** a template body contains `{{property_name}}` but `slot_instructions` has no entry for `property_name`
- **THEN** `property_name` is listed in `extra_slots`

#### Scenario: Instruction for an absent slot is flagged as orphan
- **WHEN** a template's `slot_instructions` contains an entry named `penalty` but the body has no `{{penalty}}` token
- **THEN** `penalty` is listed in `orphan_instructions`

### Requirement: Canonical Slot Placement Expectation
The system SHALL treat `sign_date` and `sign_location` as tail-allowed slots: for these two slots, a `tail_only` classification SHALL count as `present` for pass/fail purposes and SHALL NOT cause the template to fail. For all other `REQUIRED_SLOTS` entries (`party_a`, `party_b`, `subject`, `amount`, `term_start`, `term_end`, `party_a_duty`, `party_b_duty`, `penalty`, `jurisdiction`), a `tail_only` classification SHALL cause the template to fail. The body-proper set SHALL be derived from `REQUIRED_SLOTS` minus the tail-allowed pair, never authored as an independent list.

#### Scenario: sign_date in the tail does not fail the template
- **WHEN** a template body contains `{{sign_date}}` only at or after the `## 签署信息` heading and every body-proper required slot is present before it
- **THEN** the result `status` is `pass` and `sign_date` is not in `missing`

#### Scenario: party_b in the tail fails the template
- **WHEN** a template body contains `{{party_b}}` only at or after the `## 签署信息` heading
- **THEN** the result `status` is `fail` and `party_b` is in `tail_only`

### Requirement: Slot Audit CLI
The system SHALL expose the audit as `python -m src.contracts audit` with options `--type <key>` (audit a single contract class), `--json` (emit the structured report to stdout), `--strict` (exit non-zero iff any audited template is failing), and `--out <path>` (write the JSON report to a file, defaulting to `output/contract_slot_audit.json`). Without `--type`, the CLI SHALL audit every contract class in `list_contract_types()`. The default (non-`--json`) output SHALL be a human-readable table - one row per template with its status and any missing/tail-only slots - followed by an aggregate summary. `--strict` SHALL consider only missing or body-proper-misplaced required slots as failures; `extra_slots` and `orphan_instructions` SHALL be warnings that do not trigger a non-zero exit.

#### Scenario: Audit all templates prints a summary
- **WHEN** `python -m src.contracts audit` is run without `--type`
- **THEN** it prints one row per contract class and an aggregate line reporting the total, passed, and failed counts, and exits `0` when no template is failing

#### Scenario: Strict mode exits non-zero on a failing template
- **WHEN** `python -m src.contracts audit --strict` is run and at least one template has a missing or body-proper-misplaced required slot
- **THEN** the process exits with a non-zero status code

#### Scenario: JSON output is machine-readable
- **WHEN** `python -m src.contracts audit --json` is run
- **THEN** stdout is a single valid JSON object containing the per-template results and an aggregate summary

#### Scenario: Audit a single contract type
- **WHEN** `python -m src.contracts audit --type sale` is run
- **THEN** only the `sale` template is audited and reported

### Requirement: Template Regeneration Pre-Normalization Audit
`scripts/generate_contract_templates_llm.py` SHALL run `audit_body` on the LLM's raw draft output **before** calling `normalize_body`, and when the raw draft has any body-proper required slot that is missing or tail-only it SHALL print a warning naming the contract key and the omitted slots. The warning SHALL be non-blocking: the script SHALL NOT raise, SHALL still call `normalize_body`, and SHALL still write the normalized registry exactly as it does today. When the raw draft contains every body-proper required slot in the body proper, the script SHALL print no such warning.

#### Scenario: Raw draft missing a party slot warns but still normalizes
- **WHEN** the LLM returns a draft for `employment` that omits `{{party_b}}` from the body proper
- **THEN** the script prints a warning naming `employment` and `party_b`, then writes a normalized body that includes `{{party_b}}`, and exits `0`

#### Scenario: Complete raw draft produces no warning
- **WHEN** the LLM returns a draft for `sale` containing every body-proper required slot before the `## 签署信息` heading
- **THEN** the script prints no pre-normalization audit warning for `sale`

### Requirement: Audit Report Artifact
The CLI SHALL write a JSON report artifact when `--out` is given or by default to `output/contract_slot_audit.json`. The report SHALL contain an `aggregate` object with `total`, `passed`, `failed`, `failing_templates` (list of failing contract keys), and `by_slot` (a map from each `REQUIRED_SLOTS` name to the number of templates missing it), plus a `templates` array of the per-template result objects. Re-running the CLI SHALL overwrite the file.

#### Scenario: Report file is written with expected shape
- **WHEN** `python -m src.contracts audit --out output/contract_slot_audit.json` is run
- **THEN** the file exists and parses as JSON with an `aggregate` object containing `total`, `passed`, `failed`, `failing_templates`, and `by_slot`, and a `templates` array

#### Scenario: by_slot counts missing slots across templates
- **WHEN** two templates are each missing `{{party_b}}` and the report is generated
- **THEN** `aggregate.by_slot["party_b"]` equals `2`
