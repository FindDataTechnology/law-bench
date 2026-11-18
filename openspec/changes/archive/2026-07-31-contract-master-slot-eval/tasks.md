## 1. Evaluator core

- [x] 1.1 Create `src/contracts/audit.py` with the public dataclasses `TemplateAudit` (fields: `key, zh, status, coverage, present, tail_only, missing, extra_slots, orphan_instructions`) and `AuditReport` (fields: `aggregate` + `templates`); import `REQUIRED_SLOTS`, `default_slot_instructions` from `src.contracts.slots` and `SLOT_PATTERN` from `src.docs` (no redefinition)
- [x] 1.2 Define `BODY_PROPER_SLOTS` derived as `tuple(s for s in REQUIRED_SLOTS if s not in {"sign_date", "sign_location"})` and `TAIL_ALLOWED_SLOTS = ("sign_date", "sign_location")` (single source of truth from `REQUIRED_SLOTS`)
- [x] 1.3 Implement `_split_body(body)` returning `(head_slots, tail_slots)` by splitting `body` at the first `^##\s*签署信息` heading (multiline regex); when no heading exists, treat the whole body as head and tail as empty
- [x] 1.4 Implement `audit_body(body, slot_instructions) -> TemplateAudit`: classify each `REQUIRED_SLOTS` name as `present` (in head), `tail_only` (only in tail), or `missing` (neither); collect `extra_slots` (body slot names absent from `slot_instructions` names) and `orphan_instructions` (instruction names absent from body); compute `status` (fail iff any body-proper slot is `missing` or `tail_only`) and `coverage` (present body-proper / total body-proper)
- [x] 1.5 Implement `audit_template(contract_type) -> TemplateAudit`: load via `get_template(contract_type)`, pass `body` + `slot_instructions` to `audit_body`; raise `NotFoundError` for an unknown type (delegating to `get_template`)
- [x] 1.6 Implement `audit_all() -> AuditReport`: iterate `list_contract_types()`, audit each, build `aggregate` (`total, passed, failed, failing_templates, by_slot`) where `by_slot` counts `missing` occurrences per `REQUIRED_SLOTS` name

## 2. CLI

- [x] 2.1 Add an `audit` subcommand to `src/contracts/cli.py` via a `--audit`/positional path consistent with the existing Argparse style, OR refactor `_build_parser` to accept `audit` as a subcommand; options `--type`, `--json`, `--strict`, `--out` (default `output/contract_slot_audit.json`)
- [x] 2.2 Implement default (non-`--json`) output: a human-readable table - one row per template with `key`, `status`, and any `missing`/`tail_only` slot names - followed by an aggregate summary line (`total / passed / failed`)
- [x] 2.3 Implement `--json` output: print the full `AuditReport` as a single JSON object to stdout
- [x] 2.4 Implement `--strict`: exit `1` iff any audited template is failing (missing or body-proper-misplaced required slot); `extra_slots`/`orphan_instructions` do not trigger failure
- [x] 2.5 Implement `--out`: write the JSON report to the given path (default `output/contract_slot_audit.json`), creating parent dirs; overwrite on re-run
- [x] 2.6 Verify `python -m src.contracts audit --help` lists the new options and `python -m src.contracts audit` runs against the current 41-template registry

## 3. Generator integration

- [x] 3.1 In `scripts/generate_contract_templates_llm.py`, after `_call_llm(...)` returns `raw` and before `normalize_body(raw, ...)`, call `audit_body(raw, default_slot_instructions(zh))` and collect body-proper slots that are `missing` or `tail_only`
- [x] 3.2 When that list is non-empty, print `[audit] <key>: draft omitted body-proper slots [...]` (warning only - no raise, no change to the normalized body written to the registry)
- [x] 3.3 Confirm the generator still exits `0` on a draft missing slots (fallback-to-existing-body behavior unchanged) and that a complete draft prints no warning

## 4. Tests

- [x] 4.1 Create `tests/test_contract_slot_audit.py` (hermetic - no LLM, no DB, no network): assert `audit_body` classifies a synthetic body with all 12 slots in the head as `pass` with empty `missing`/`tail_only`/`extra_slots`/`orphan_instructions`
- [x] 4.2 Assert a body omitting `{{party_b}}` lists `party_b` in `missing`, `status == fail`, `coverage < 1.0`
- [x] 4.3 Assert a body with `{{party_a}}` only after `## 签署信息` lists `party_a` in `tail_only` and `status == fail`; assert `{{sign_date}}` only after `## 签署信息` does NOT fail (tail-allowed)
- [x] 4.4 Assert `extra_slots` flags a body-only `{{property_name}}` and `orphan_instructions` flags an instruction for a slot absent from the body
- [x] 4.5 Assert `audit_all()` aggregate: `by_slot["party_b"]` increments per template missing it; `failing_templates` lists failing keys
- [x] 4.6 Assert CLI behavior via `subprocess`/`main(argv)`: `audit` default prints a summary and exits `0`; `--strict` exits non-zero when a synthetic failing template is present; `--json` emits valid JSON; `--type sale` audits one template
- [x] 4.7 Regression test: `audit_all()` over the real committed `src/contracts/data/contracts.json` has `failed == 0` (guards future edits from dropping a required slot)
- [x] 4.8 Assert `--out` writes `output/contract_slot_audit.json` with the `aggregate` (`total, passed, failed, failing_templates, by_slot`) and `templates` keys

## 5. Verification

- [x] 5.1 Run `uv run pytest tests/test_contract_slot_audit.py -q` and confirm all tests pass
- [x] 5.2 Run `uv run python -m src.contracts audit` and confirm the 41-template registry reports all-pass
- [x] 5.3 Run `uv run python -m src.contracts audit --json --out output/contract_slot_audit.json` and confirm the report file is written and parses
- [x] 5.4 Run `openspec validate contract-master-slot-eval --strict` and confirm the change validates cleanly
