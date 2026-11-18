## Context

Contract 母版 live in `src/contracts/data/contracts.json` - 41 entries, each `{key, zh, body, slot_instructions}` where `body` is Markdown containing `{{slot}}` placeholders. Two scripts produce them:

- `scripts/seed_contract_templates.py` - hand-authored skeleton body with all 12 `{{slot}}` tokens.
- `scripts/generate_contract_templates_llm.py` - asks the `DRAFTER_MODEL` LLM to draft a type-specific body containing exactly the 12 slots, then runs `normalize_body(raw, REQUIRED_SLOTS)` which (a) strips unknown `{{slot}}` tokens and (b) **appends** any missing required slot to a trailing `## 签署信息` block.

The slot model's source of truth: `src/contracts/slots.py` (`REQUIRED_SLOTS` - the 12 canonical names; `default_slot_instructions(zh)` - the manifest), and `src/docs/slots.py` (`SLOT_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][\w-]*)\s*\}\}")`). The only existing completeness check, `check_slot_consistency(contract_type)`, compares the template's slot set against the `slot_instructions` manifest names (missing-vs-extra *instructions*) - it does not reference `REQUIRED_SLOTS`, does not look at *where* a slot appears, and has no CLI/report.

Inspection confirms the gap this change targets: all 41 templates have `sign_date`/`sign_location` appearing **only** in the `## 签署信息` tail block, and `normalize_body` would silently move `party_a`/`party_b`/`term_*` there too if a future LLM draft omitted them - so "the slot set is complete" can hide a semantically broken 母版. Constraints: the `test-suite` spec mandates hermetic tests (no network, no LLM, no shared DB), so the evaluator MUST be deterministic and dependency-free; it runs locally (macOS) and in the Linux/k3s container.

## Goals / Non-Goals

**Goals:**
- Answer "which contract 母版 are missing 甲方/乙方/时间 (or any canonical) slots, and which only have them papered into the 签署信息 tail?" - deterministically, no LLM.
- Classify each canonical slot per template as `present` (in the body proper), `tail_only` (only in the `## 签署信息` block), or `missing`; plus `extra_slots` (body slots with no instruction) and `orphan_instructions` (instructions for slots absent from the body).
- Expose the audit as a Python API, a `python -m src.contracts audit` CLI (human table + `--json` + `--strict` gate), and a JSON report artifact under `output/`.
- Surface pre-normalization omissions in `generate_contract_templates_llm.py` so the drafter's quality is visible instead of hidden by `normalize_body`.

**Non-Goals:**
- LLM-judge scoring of clause prose quality (owned by `evaluation-rules`' GEval rubric evaluator).
- Auto-rewriting/fixing template bodies to repair gaps.
- Auditing clause-assembled contracts from `src/clauses/assemble.py` (separate assembly path; the API takes a raw body so it can be reused later without redesign).
- A web UI for the audit (deferred follow-up).

## Decisions

### D1: Deterministic static analyzer, not an LLM judge
Slot presence and placement are structural facts recoverable by `SLOT_PATTERN` + section parsing. An LLM judge (extending `evaluation-rules`' GEval) would be flaky, slow, costly, and would violate the `test-suite` hermetic-execution requirement. **Alternative considered**: reuse the GEval judge with a "slot completeness" criterion - rejected for the above reasons; the LLM judge remains the right tool for prose quality, not slot presence.

### D2: Three-tier slot classification + extra/orphan, reusing the existing source of truth
`audit_template(contract_type)` returns, for each of the 12 `REQUIRED_SLOTS`: `present`, `tail_only`, or `missing`. It also returns `extra_slots` (names in `body` not in `slot_instructions`) and `orphan_instructions` (manifest names not in `body`). The body-proper vs. tail split is computed by finding the `## 签署信息` heading (regex `^##\s*签署信息`, multiline) and partitioning `SLOT_PATTERN.findall(body)` into before/after. `REQUIRED_SLOTS`, `default_slot_instructions`, and `SLOT_PATTERN` are **imported**, never redefined - no parallel list that can drift.

### D3: Canonical expected-placement map (avoids false positives on sign_date/sign_location)
The skeleton seeder intentionally puts `sign_date`/`sign_location` in the `## 签署信息` tail - that is correct contract structure, not a defect. So `tail_only` is only a **failing** condition for the body-proper set: `party_a, party_b, subject, amount, term_start, term_end, party_a_duty, party_b_duty, penalty, jurisdiction`. For `sign_date`/`sign_location`, `tail_only` is acceptable (counts as `present` for pass/fail). The map is a single tuple `BODY_PROPER_SLOTS` derived from `REQUIRED_SLOTS` minus the tail-allowed pair, so it cannot drift from `REQUIRED_SLOTS`. **Alternative considered**: treat all `tail_only` as failures - rejected (would flag all 41 templates on `sign_date`/`sign_location`, drowning the real signal).

### D4: CLI as a subcommand on the existing `src/contracts/cli.py`
`python -m src.contracts audit [--type <key>] [--json] [--strict] [--out PATH]` mirrors the existing `python -m src.contracts <type>` entrypoint and Argparse style. `--strict` exits non-zero iff any audited template has a missing or body-proper-misplaced required slot (extras/orphans are warnings, not failures). `--json` emits the structured report to stdout; default prints a human table + aggregate summary. `--out` writes the JSON report to disk (default `output/contract_slot_audit.json`). **Alternative considered**: a separate `python -m src.contracts.audit` module - rejected (one entrypoint is simpler and matches the existing CLI surface).

### D5: Generator integration is warn-only and non-blocking
`generate_contract_templates_llm.py` calls `audit_body(raw, REQUIRED_SLOTS)` on the LLM's raw output **before** `normalize_body` and prints `[audit] <key>: draft omitted body-proper slots [...]` when body-proper slots are missing or tail-only in the raw draft. It does not raise or change the written registry - preserving the existing non-destructive fallback-to-existing-body behavior. **Alternative considered**: hard-fail the generator on audit failure - rejected (would break the resilient fallback flow; the `--strict` CLI is the gate for CI).

### D6: Report shape
Per-template object: `{key, zh, status: "pass"|"fail", coverage: "<present_body_proper>/<required_body_proper>", present: [...], tail_only: [...], missing: [...], extra_slots: [...], orphan_instructions: [...]}`. Aggregate: `{generated_at, total, passed, failed, failing_templates: [...], by_slot: {<slot>: <missing_count>}}`. `generated_at` is supplied by the CLI caller (the evaluator itself is `Date.now()`-free so it stays hermetic/testable).

## Risks / Trade-offs

- **[normalize_body guarantees presence, so the committed registry may always pass]** -> That is the intended regression-gate behavior; the *pre-normalization* generator check (D5) is where new draft gaps surface. A regression test asserts the current 41-template registry passes, so a future edit that drops a slot trips CI.
- **[Semantic-placement heuristic false positives]** -> Mitigated by D3's expected-placement map; only body-proper slots fail when tail-only. `sign_date`/`sign_location` are explicitly tail-allowed.
- **[Drift between audit expectations and the slot model]** -> Mitigated by D2: every constant is imported from `src.contracts.slots` / `src.docs`; no redefinition.
- **[Auditing only the registry misses assembled contracts]** -> Accepted as a Non-Goal; `audit_body(body, ...)` takes an arbitrary body string so `src/clauses/` can reuse it later without API change.
- **[`## 签署信息` heading variant formatting]** -> Regex `^##\s*签署信息` (multiline) tolerates trailing whitespace; if a template lacks the heading entirely, the whole body is treated as body-proper (no tail) - a safe default that still flags truly missing slots.
