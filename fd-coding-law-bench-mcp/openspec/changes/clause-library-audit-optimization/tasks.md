# Clause Library Audit & Optimization Tasks

**Schema**: spec-driven | **Scope**: P0-P2 audit (~3378 ready clauses) + P3 dedupe + re-eval gate

## Structured Task List

| # | Status | Subject |
|---|--------|---------|
| 1 | [ ] | Build `src/clauses/audit.py`: classify/rewrite/verify prompt templates + region-lint regex |
| 2 | [ ] | Build `scripts/audit_clauses.py` driver (mirrors self_iterate.py structure: 3-model classify trio -> single rewrite -> verify -> clause_update) |
| 3 | [ ] | Deterministic dedupe pass: 171 exact-dup tagged -> `rejected` via `clause_review` (keep lowest id) |
| 4 | [ ] | Region lint baseline: log residual province/city names per type BEFORE audit (documents starting point) |
| 5 | [ ] | Dry-run audit on employment base (4 clauses, highest blast radius) - validate rewrite rules end-to-end |
| 6 | [ ] | P0 audit: 329 base-ready clauses across 43 types |
| 7 | [ ] | P1 audit: 73 custom-ready clauses (check custom<->base shadowing post-rewrite) |
| 8 | [ ] | P2 audit: 2976 tagged-ready clauses (largest batch; throttle to relay 12-concurrent) |
| 9 | [ ] | Post-rewrite region lint: confirm residual province names -> 0 on rewritten clauses |
| 10 | [ ] | Re-run `self_iterate` across all 43 types (3-judge serial, FAIL_CONF_THRESHOLD=0.6) |
| 11 | [ ] | Re-eval gate: confirm all-pass >= 39/43 (no regression); log any regressed type |
| 12 | [ ] | Stretch: investigate 4 stuck types (lease/land_transfer/film_production/service) post-audit |
| 13 | [ ] | Update dashboard pipeline_runs with audit-batch rows (source=clause_audit) |
| 14 | [ ] | Update memory: clause-library-audit outcome + residual issues |
| 15 | [ ] | Archive OpenSpec change (validate passes) |

## Task Details

### Task 1 - audit module
`src/clauses/audit.py` exports:
- `classify_clause(body, contract_type, section) -> {verdict, suggested_fix, confidence}` - single-model
- `rewrite_clause(body, verdict) -> new_body` - applies region/slot/artifact rules
- `verify_rewrite(orig, rewritten) -> {fixed, legal_preserved}`
- `region_lint(body) -> list[str]` - residual province/city matches
- Prompt constants for the 3 roles; judge factory reuses `src/eval/judge.py` relay client.

### Task 2 - driver
`scripts/audit_clauses.py`:
- `--tier {p0,p1,p2,p3,all}` selector (P3 = dedupe-only, no LLM)
- `--dry-run` prints verdicts/rewrites without writing
- `--type <key>` to scope to one contract type (for the employment pilot, task 5)
- Persists each audited clause's verdict + rewrite to `output/audit/<type>_<id>.json` for diff/rollback
- Writes rewritten body via `clause_update`; marks `tags.audit = {models, verdict, ts}` (no schema change, just a jsonb key)

### Task 3 - dedupe
Pure SQL + `clause_review(reject)` loop. Idempotent (skip already-rejected). No LLM. ~171 rows.

### Task 5 - employment pilot
Run the full pipeline on the 4 employment base clauses (6969, 6971, 6974, 6976) first. Generate an employment contract before/after, diff it, confirm the Shenzhen regs are genericized and no legal point dropped. Gate the full P0-P2 run on this pilot passing.

### Task 10-11 - re-eval gate
Re-run must use the SAME judge trio and rubric versions as V4/V5 (kimi-k3 + glm-5.2 + deepseek-v3, latest-version rubric per type, FAIL_CONF_THRESHOLD=0.6) so the comparison is apples-to-apples. A type "regresses" if it was all-pass and now isn't.
