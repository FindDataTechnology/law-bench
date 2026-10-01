# V4 Sale Pilot - Final Results

## Date: 2026-08-07

## Final Score: 10/10 ALL PASS (Score=1.0)

| Criterion | Verdict | Conf |
|-----------|---------|------|
| party_identification | ✅ pass | 1.0 |
| governing_law_present | ✅ pass | 0.67 |
| clause_completeness | ✅ pass | 0.67 |
| legal_citation_accuracy | ✅ pass | 1.0 |
| ownership_transfer | ✅ pass | 1.0 |
| risk_transfer_point | ✅ pass | 1.0 |
| inspection_period | ✅ pass | 1.0 |
| defect_warranty | ✅ pass | 1.0 |
| ownership_retention | ✅ pass | 1.0 |
| legal_basis_citation | ✅ pass | 1.0 |

## What Worked (Key Insights)

### 1. **legal_topic self-iteration loop works**
The closed loop: FAIL → map to legal_topic → generate targeted clause → re-eval → PASS
- Proved effective for sale (3/10 → 10/10 in 4 rounds)

### 2. **Multi-judge evaluation requires serial execution**
- `max_workers=1` to avoid relay rate limits (~7 req/min on new relay)
- Parallel execution (8 workers × 3 judges) blows rate limit → RetryError masquerades as FAIL

### 3. **Custom override drops rich base content** (critical lesson)
When generating a custom clause for a section, **MERGE the base's other substantive clauses** into it, don't replace wholesale.

Example: Our inspection_period custom (section=履行期限) replaced the base 履行期限 clause which had risk-transfer language → risk_transfer_point went unanimous FAIL until we merged risk+inspection into one clause.

### 4. **Contradictions break judges**
Judges see "所有权自交付时转移" (id=565) + "未付清全部价款前保留" (id=566) as contradictory, even with "以本条约定为准" clarification.

**Solution**: Remove the default from 合同标的 entirely; let 价款及支付 (retention) be the ONLY ownership rule.

### 5. **Relay migration needed**
Old relay (linjie.love): 20 req/min + PAT pool exhaustion → unusable for multi-judge
New relay (<relay-ip>): ~7 req/min, unlimited daily → works for serial eval

## Working Clause Structure (sale)

| Section | Clause ID | legal_topic | Content |
|---------|-----------|-------------|---------|
| 合同标的 | 565 | ownership_transfer | Subject matter only (NO ownership transfer - retention covers it) |
| 价款及支付 | 566 | ownership_retention | Retention of title (ONLY ownership rule) |
| 履行期限 | 568 | risk_transfer_point | Deadline + risk transfer + inspection period |

## Why lease self-iteration failed (vs sale)

- Sale: we **manually wrote** precise clauses based on judge feedback (4 rounds of human iteration)
- Lease: **LLM-generated** clauses were lower quality → judges saw contradictions/missing content → oscillated 3-4/10

**Lesson**: LLM generation needs better prompting or human review for quality clauses.

## Next Steps

1. **Batch self-iteration for remaining 42 types** (blocked by relay rate limit ~7 req/min)
   - Each type: ~15-20 min (10 criteria × 3 judges × 4 rounds, serial)
   - 42 types × 20 min = ~14 hours total

2. **Improve LLM generation quality** for self-iteration
   - Better prompts with explicit contradiction checks
   - Show judge the full contract context before generating

3. **Alternative: human-authored seed clauses** for each type (like we did for sale)
   - Faster than LLM iteration if we know the legal requirements
