## ADDED Requirements

### Requirement: Multi-model clause audit classification

The system MUST classify each assembly-ready clause (P0-P2: base/custom/tagged-ready) via three LLM models (kimi-k3, glm-5.2, deepseek-v3) voting by majority into exactly one of: `ok`, `region_leak`, `missing_slot`, `wrong_scenario`, `extraction_artifact`, `duplicate`, each verdict carrying a `suggested_fix` and `confidence`.

#### Scenario: Three-model majority on a region-leaking clause
- **WHEN** the audit classifies employment base clause id=6971 ("按照《深圳市员工工资支付条例》…")
- **THEN** at least 2 of 3 models return `region_leak` with suggested_fix naming the national-law fallback
- **AND** the merged verdict is `region_leak`

#### Scenario: Statutory default is not flagged missing_slot
- **WHEN** the audit classifies real_estate_sale clause "设计变更应在批准之日起10日内书面通知"
- **THEN** the merged verdict is `ok` (statutory time limit under 《商品房销售管理办法》 art. 24, not a commercial blank)

#### Scenario: Tie or low-confidence defers to keep
- **WHEN** the three verdicts do not yield a majority (all differ) OR confidence < 0.6
- **THEN** the clause is marked `uncertain`, kept as-is, and logged for manual review

### Requirement: Region genericization on rewrite

The system MUST rewrite region-leaking clauses by replacing provincial regulation references with the corresponding national law, or with the generic fallback "按照国家及当地有关规定执行", WITHOUT deleting the underlying obligation.

#### Scenario: Provincial regulation replaced by national law
- **WHEN** a clause cites 《广东省工资支付条例》
- **THEN** the rewrite replaces it with 《中华人民共和国劳动法》/《中华人民共和国劳动合同法》 as applicable, keeping the duty intact

#### Scenario: No national equivalent uses generic fallback
- **WHEN** a clause cites 《北京市建筑垃圾处置管理规定》 with no national-law counterpart
- **THEN** the rewrite replaces the citation with "按照国家及当地有关规定执行"

#### Scenario: Obligation preserved
- **WHEN** a region-leaking clause is rewritten
- **THEN** the verify pass confirms the legal obligation (duty/right/penalty) is present in the rewritten body

### Requirement: Slot-ification of commercial blanks

The system MUST convert hardcoded commercial values (amounts, parties, negotiable periods, percentages) into `{{slot}}` placeholders, while keeping statutory defaults hardcoded with a `law_refs` citation.

#### Scenario: Commercial amount becomes a slot
- **WHEN** a clause contains "违约金为合同总额的20%" where 20% is a negotiable commercial term
- **THEN** the rewrite produces "违约金为合同总额的{{penalty_pct}}" and `slot_instructions` is rederived for the new slot

#### Scenario: Statutory ratio stays hardcoded
- **WHEN** a clause contains a ratio mandated by law
- **THEN** the rewrite keeps it hardcoded and adds the citing article to `law_refs`

### Requirement: Rewrite verification

The system MUST verify each rewritten clause with a different model than the rewriter, checking that the flagged defect is fixed and no legal point was dropped. Failed verification keeps the original body.

#### Scenario: Verify passes
- **WHEN** the rewrite of id=6971 removes Shenzhen refs and the verify model confirms the wage-payment duty remains
- **THEN** `clause_update` writes the new body (sets `manual=true`)

#### Scenario: Verify fails
- **WHEN** the verify model reports a legal point was dropped
- **THEN** the original body is kept, the clause is logged to `output/audit/*_failed.json` for manual review

### Requirement: Deterministic duplicate rejection

The system MUST mark fully-identical duplicate clauses (same `body_hash`) as `rejected` via `clause_review`, keeping only the lowest-`id` canonical, without invoking any LLM. Rejected clauses are recoverable via re-approval.

#### Scenario: Reject exact duplicates
- **WHEN** two or more tagged clauses share a `body_hash`
- **THEN** all but the lowest `id` are set to `rejected` status across all their tag dims
- **AND** no LLM call is made for deduplication

### Requirement: Region lint quality metric

The system MUST run a deterministic regex pass over audited clause bodies counting residual province/city names, and surface the per-type aggregate alongside evaluation scores as a quality metric (not a hard block).

#### Scenario: Lint after rewrite
- **WHEN** the audit batch completes for a contract type
- **THEN** a region-lint report lists residual province/city matches per clause and a per-type total
- **AND** rewritten clauses show 0 residual matches (statutory national-level names excluded)

### Requirement: Re-evaluation no-regression gate

The system MUST re-run the self-iteration pipeline across all 43 contract types after the audit and confirm the all-pass count does not regress below the V4/V5 baseline of 39/43.

#### Scenario: No regression
- **WHEN** the post-audit self-iteration completes
- **THEN** at least 39 of 43 types achieve all-pass with the same judge trio and rubric versions as V4/V5

#### Scenario: Regression triggers investigation
- **WHEN** a type that was all-pass in V4/V5 is no longer all-pass
- **THEN** the pipeline logs the regressed type and diffs its pre/post assembled contract
- **AND** flags any custom override shadowing an improved base for re-merge or retirement
