# Design V4 Tags and Self-Iteration Tasks

**Schema**: spec-driven | **Total Tasks**: 15 | **Phase 1a**: Tag Schema Foundation

## Structured Task List

| # | Status | Subject |
|---|--------|---------|
| 1 | [x] | Delete dead dimensions (strength/risk/mandatory) |
| 2 | [x] | Register legal_topic dimension for all types |
| 3 | [x] | Implement stance alias mapping (pro_seller→pro_a) |
| 4 | [x] | Modify evaluate_node for parallel judge execution |
| 5 | [x] | Modify scoring logic for multi-judge verdicts |
| 6 | [x] | Graceful degradation handling on judge failure |
| 7 | [x] | Create batch legal_topic tagging script |
| 8 | [x] | Verify coverage completeness script |
| 9 | [x] | Run targeted self-iteration on sale pilot |
| 10 | [x] | Analyze v4 vs v3 results comparison |
| 11 | [x] | Apply legal_topic backfill to all 43 types |
| 12 | [x] | **BREAKTHROUGH** sale self-iteration with new relay: 6/10 → 8/10 → **10/10 ALL PASS** (Score=1.0, 3 judges unanimous) |
| 13 | [x] | Run self-iteration on 19 named contracts (relay: ~7 req/min, unlimited daily) |
| 13b | [x] | Run self-iteration on 24 unnamed contracts — FINAL: 18/43 all-pass overall. Of 11 transient-zero types re-run after the `load_dotenv(override=True)` credential fix: 5 now ALL PASS (merger_acquisition, ppp_project, talent_agency, trust, vam_agreement); 6 partial (employment 10/11, land_transfer 10/11, tourism_service 10/11, equity_holding_in_trust 9/10, company_formation 7/9, film_production 8/11) |
| 14 | [x] | Update MCP documentation (v4-sale-pilot-results.md) |
| 15 | [x] | Archive OpenSpec change (spec validation fixed: 7 MODIFIED reqs rewritten as SHALL/MUST prose; `openspec validate` passes) |

---

## Phase 1a: Tag Schema V4 Foundation

### Task 1: Delete dead dimensions from starter vocab

**Location**: `/Users/chengsishi/law-template/src/clauses/tags.py`

**Steps**:
1. Update `_STANDARD_TAG_VALUES` to remove `strength`, `risk`, `mandatory`
2. Keep only `source` and `stance` as universal dims
3. Ensure type-specific dims (from DB) are merged correctly in `load_vocab_from_db()`

**Acceptance Criteria**:
- `tag_vocab_list(contract_type=None)` returns `{source, stance}` only
- Old clauses with dead dims keep them (backward compatible)

---

### Task 2: Register legal_topic dimension for all types

**Location**: `/Users/chengsishi/law-template/src/clauses/tags.py`, `/Users/chengsishi/law-template/src/eval/rubric_crud.py`

**Steps**:
1. Create function `register_legal_topic_dims(contract_type, criteria_names)`
2. For each contract type, extract rubric criterion names → legal_topic values
3. Call this function during init to register all 43 types' legal_topic dims

**Acceptance Criteria**:
- `tag_vocab_list(contract_type="sale")` includes `"legal_topic": ["party_identification", ...]` (10 topics)
- All 43 types have legal_topic registered

---

### Task 3: Implement stance alias mapping

**Location**: `/Users/chengsishi/law-template/src/clauses/tags.py`

**Steps**:
1. Add `STANCE_ALIASES = {"pro_seller": "pro_a", "pro_buyer": "pro_b"}` constant
2. Modify `tag_validate()` to resolve aliases before validation
3. Modify `_select_clauses()` to match both original and aliased values when filtering custom clauses

**Acceptance Criteria**:
- User input `stance="pro_seller"` resolves internally to `"pro_a"`
- Custom clause filter matches both `stance: pro_a` AND `stance: pro_seller` rows

---

## Phase 1b: Multi-Judge Evaluation

### Task 4: Modify evaluate_node for parallel execution

**Location**: `/Users/chengsishi/law-template/fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/pipeline/graph.py`

**Steps**:
1. Create new function `evaluate_with_judges(contract_text, rubric_name, judge_models=["kimi-k3", "glm-5", "deepseek"])`
2. Use ThreadPoolExecutor to run N judges concurrently
3. Aggregate verdicts using majority voting
4. Return structure with `per_judge_breakdown` and `confidence` per criterion

**Acceptance Criteria**:
- 3-judge eval on sale completes in ~same wall-clock time as single judge
- Output includes confidence scores (1.0 or 0.67) per criterion

---

### Task 5: Modify scoring logic for multi-judge verdicts

**Location**: `/Users/chengsishi/law-template/src/eval/scoring.py`

**Steps**:
1. Update `evaluate_contract()` signature to accept `judge_models` parameter
2. Add majority vote aggregation logic
3. Compute score = 1.0 ONLY if ALL criteria pass AND min(confidence) ≥ 0.67
4. Include `n_unanimous_pass`, `n_majority_pass`, `n_failures` summary fields

**Acceptance Criteria**:
- Score is 1.0 only when unanimous majority agrees on all-pass
- Summary reflects breakdown of 3/3 vs 2/1 agreements

---

### Task 6: Graceful degradation handling

**Location**: `/Users/chengsishi/law-template/fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/pipeline/graph.py`

**Steps**:
1. Wrap each judge call in try-except
2. Track which judges succeeded/failed
3. If <3 available, downgrade strategy:
   - 2 available: require unanimous (2/2)
   - 1 available: flag low_confidence=true, skip auto-reject
   - 0 available: fail fast with error

**Acceptance Criteria**:
- Single API failure doesn't crash pipeline
- Results include `low_confidence=true` flag when needed

---

## Phase 1c: legal_topic Backfill

### Task 7: Create sub-agent for batch tagging

**Location**: `/Users/chengsishi/law-template/scripts/backfill_legal_topics.py` (new file)

**Steps**:
1. Read all clauses for a contract type via `clause_list()`
2. Read rubric criteria via `rubric_get()`
3. For each clause, prompt LLM: "Which rubric criterion does this clause primarily address?"
4. Write back via `clause_update(clause_id, tags={...legal_topic: topic})`
5. Batch process by contract type (one agent per type)

**Acceptance Criteria**:
- Sale's 1288 tagged clauses all get legal_topic assigned
- Coverage report shows each of 10 topics has ≥1 clause (or reports gap)

---

### Task 8: Verify coverage completeness

**Location**: `/Users/chengsishi/law-template/scripts/verify_topic_coverage.py` (new file)

**Steps**:
1. Get rubric criteria count for a contract type
2. Query DB for clauses grouped by legal_topic
3. Report gaps where topic count = 0
4. Exit non-zero if any gaps exist (for CI checking)

**Acceptance Criteria**:
- Script outputs JSON: `{coverage: {topic: count}, gaps: [topic: ...]}`
- Sale exits 0 after successful backfill

---

## Phase 2: Named Contract Pilot (sale)

### Task 9: Run targeted self-iteration on sale

**Location**: `/Users/chengsishi/law-template/fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/tools/auto_pipeline.py`

**Steps**:
1. Invoke `auto_pipeline_run(contract_type="sale", stance="balanced", rubric="contract_sale_v3")`
2. Pipeline should now use multi-judge eval + coverage analysis
3. Monitor iterations until max_iterations reached or all_pass=true
4. Log coverage gap resolution per iteration

**Acceptance Criteria**:
- sale balanced evaluates to score=1.0 (all_pass=true)
- Coverage gaps resolved (ownership_transfer, inspection_period, ownership_retention)
- Pipeline uses 3 models (kimi-k3/glm-5/deepseek)

---

### Task 10: Analyze results and compare to baseline

**Location**: Analysis script or manual review

**Steps**:
1. Compare v4 results (multi-judge) vs v3 baseline (single judge kimi-k3)
2. Check if failures changed (was 7/10, target 10/10)
3. Document which clauses were newly generated vs excluded
4. Record token cost increase from 3x judges

**Acceptance Criteria**:
- Report: `v4_score=1.0, v3_baseline=0.7, token_cost_multiplier=2.8x`
- Qualitative review confirms new clauses are legally accurate

---

## Phase 3: Batch Application

### Task 11: Apply legal_topic backfill to all 43 types

**Location**: Sub-agent loop over contract types

**Steps**:
1. Loop through all 43 contract types from `type_metadata()`
2. For each type, invoke backfill agent (Phase 1c Task 1)
3. Run coverage verification (Phase 1c Task 2)
4. Aggregate statistics: total clauses tagged, coverage gaps remaining

**Acceptance Criteria**:
- 43 types processed, all get legal_topic assignments
- Final report: X% types have full coverage, Y gaps remaining

---

### Task 12: Run self-iteration on named contracts (19 types)

**Location**: Batch script invoking `auto_pipeline_run` for each named type

**Steps**:
1. For each named contract type (19), run: `auto_pipeline_run(type, stance="balanced", max_iterations=3)`
2. Set `max_iterations=3` based on classification
3. Collect results: score, all_pass, n_generations
4. Skip types that already achieved all_pass

**Acceptance Criteria**:
- All 19 named contracts evaluated
- Majority achieve score=1.0 (target >70%)
- Named contracts use Civil Code article citations

---

### Task 13: Run self-iteration on unnamed contracts (24 types)

**Location**: Batch script invoking `auto_pipeline_run` with conservative settings

**Steps**:
1. For each unnamed contract type (24), run: `auto_pipeline_run(type, stance="balanced", max_iterations=5)`
2. Set `max_iterations=5`, `auto_reject_threshold=5` based on classification
3. Collect results similar to named contracts
4. Flag types that still fail after 5 iterations for manual review

**Acceptance Criteria**:
- All 24 unnamed contracts evaluated
- Target >50% achieve score=1.0
- Remaining failures logged for human review

---

## Documentation & Cleanup

### Task 14: Update MCP tool documentation

**Location**: `/Users/chengsishi/law-template/docs/api-evaluate.md`

**Steps**:
1. Document new multi-judge evaluation parameters
2. Document legal_topic dimension in tag examples
3. Document stance aliasing behavior
4. Update schema diagrams showing v4 tag structure

**Acceptance Criteria**:
- Docs reflect v4 capabilities
- Example API calls show correct usage

---

### Task 15: Archive OpenSpec change

**Location**: Via `openspec archive-change` command

**Steps**:
1. After all implementation complete, archive change
2. Move specs/design/tasks to `openspec/archive/`
3. Remove live spec folders (they're migrated to main codebase)

**Acceptance Criteria**:
- Change archived successfully
- No dangling references in codebase
