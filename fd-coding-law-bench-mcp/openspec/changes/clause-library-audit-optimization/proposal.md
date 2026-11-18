## Why

The clause library holds **6433 clauses** across 43 contract types, but a ground-truth scan reveals three systemic quality defects that leak into assembled contracts:

1. **Region leakage (190 clauses, 112 assembly-ready).** Provincial/city regulations are hardcoded into clause bodies. The worst offender is `employment` **base** (ids 6969-6976) - the entire 母版 cites 《深圳市员工工资支付条例》《广东省工资支付条例》, so *every* generated employment contract is Shenzhen-specific despite `region` being provenance-only (see `clause-region-is-wrong-axis` memory). `tagged` clauses carry 《北京市建筑垃圾处置管理规定》《天津市商品住宅质量保证书》 etc.

2. **Missing slots (1035 clauses with zero `{{slot}}`).** Regex catches ~60 obvious hardcoded values, but sampling proves a one-size rule fails: `id=2132` "设计变更应在批准之日起10日内书面通知" is the *statutory* 10-day limit under 《商品房销售管理办法》 art. 24 and must stay hardcoded, while commercial blanks (amounts, parties, periods) should become `{{slot}}`. Distinguishing statutory default from commercial blank requires LLM judgment - exactly the gap to close.

3. **Inappropriate / bloated tagged set.** `tagged` holds 5664 clauses (88% of library); `sale/权利义务` alone has **169 variants** (assembly picks 1, 168 are noise that also pollute `search_clauses` RAG). 71 fully-identical `body_hash` groups = 171 duplicate clauses. Narrow-scenario clauses (e.g. 建筑垃圾清运) sit in general sections and can shadow general clauses.

Current evaluation measures only rubric completeness/legality - it is blind to region leakage and slot quality, so these defects persist undetected. A one-time LLM-driven audit + rewrite, scoped to clauses that actually enter assembly, then re-evaluated against the 39/43 all-pass baseline, will raise library quality without regressing the V4/V5 scores.

## What Changes

- **NEW** Multi-model audit pipeline: 3 models (kimi-k3, glm-5.2, deepseek-v3) classify each clause via majority vote into `ok | region_leak | missing_slot | wrong_scenario | extraction_artifact | duplicate`, with a suggested fix
- **NEW** Single-model rewrite pass with three rules:
  - **Region**: generalize provincial regulation references to national law + generic fallback ("按当地有关规定执行") - never delete (preserves the obligation)
  - **Slot**: commercial blanks (amounts/parties/periods/percentages) -> `{{slot}}`; statutory defaults (legal time limits, mandatory ratios) stay hardcoded
  - **Cleanup**: remove 示范文本 extraction artifacts (合同编号 headers, signing-place boilerplate)
- **NEW** Rewrite verification: a different model re-audits the rewritten body to confirm the defect is fixed and no legal point was dropped
- **NEW** Deterministic dedupe: 171 fully-identical `body_hash` clauses marked `rejected` (recoverable, not deleted) - no LLM cost
- **NEW** Region lint gate: post-rewrite regex pass counts residual province/city names per clause; surfaced as a quality metric alongside eval scores (complements rubric-only evaluation)
- **MODIFIED** All clause bodies rewritten via `clause_update` (sets `manual=true` so re-extraction never overwrites; `slot_instructions`/`body_hash`/`law_refs` auto-rederived)
- **NEW** Re-evaluation gate: re-run `self_iterate` across all 43 types; baseline 39/43 all-pass MUST NOT regress, and the 4 stuck types (lease 9/10, land_transfer 10/11, film_production 9/11, service 9/11) are stretch targets to unblock

## Scope Decisions (confirmed)

1. **Audit scope = P0-P2 only** (~3780 clauses: base 329 + custom 73 + tagged-ready 2976). The 2688 dormant (non-ready) tagged clauses are NOT LLM-audited; they get deterministic dedupe only.
2. **Region rewrite = generalize, not delete.** Provincial refs -> national law + "按当地有关规定执行".
3. **Dedupe = mark `rejected`, never hard-delete.** Fully-identical duplicates (171) and near-duplicate dormant variants are rejected so they drop from assembly but remain recoverable via re-approval.

## Capabilities

### New Capabilities
- `clause-audit-optimization`: The LLM audit pipeline (classify -> rewrite -> verify), region genericization rule, slot-ification rule, deterministic dedupe, and region lint gate

### Modified Capabilities
- `clause-library`: clause bodies and `manual`/`slot_instructions`/`body_hash` fields updated by the audit; dormant tagged variants rejected
- `auto-iteration-pipeline`: re-evaluation gate added as a post-optimization verification step

## Impact

- **Code**: new `scripts/audit_clauses.py` (driver, mirrors `scripts/self_iterate.py`), new `src/clauses/audit.py` (classify/rewrite/verify prompts + region-lint regex), `src/clauses/store.py` (`clause_update` already supports body rewrite)
- **Database**: `clauses` table - body rewrites on ~3780 rows (P0-P2), `tag_review` set to `rejected` on ~171 duplicate + dormant-near-dup rows; NO schema change
- **APIs**: no MCP tool changes (`clause_update` + `clause_review` already expose what's needed); optional new `audit_status` read endpoint later
- **Dependencies**: 3 LLM judge endpoints via litellm relay (kimi-k3, glm-5.2, deepseek-v3) - same as V4/V5 self-iteration
- **Data**: ~3780 clauses audited/rewritten; estimated 15-25% flagged for rewrite (~570-950 rewrites); 171 duplicates rejected
- **Cost/time**: ~11k classify calls + ~1.5k rewrite/verify calls; relay 12-concurrent ceiling => ~40-60 min total; comparable to the 43-type self-iteration batch
- **Re-eval**: full 43-type `self_iterate` re-run afterward (~existing batch duration) to confirm no regression
