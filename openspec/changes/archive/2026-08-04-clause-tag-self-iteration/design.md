## Overview

Automated clause/tag iteration system that analyzes pipeline evaluation results and automatically applies high-confidence improvements to the clauses corpus.

## Architecture

```
pipeline_runs (historical data)
          ↓
clause-iteration-analyzer
          ↓
recommendations.json (excluded IDs, reject counts, confidence scores)
          ↓
auto-executor (--dry-run first, then apply)
          ↓
clauses.tag_review + automatic updates
```

## Components

### 1. Clause Iteration Analyzer (`scripts/analyze_clause_iteration.py`)

**Purpose**: Analyze historical pipeline runs to identify improvement opportunities.

**Input**: Last N pipeline runs (default: 50).

**Output**: JSON report with recommendations.

**Key functions**:
- `analyze_exclude_patterns()`: Find clauses frequently excluded during self-heal
- `analyze_recommendations()`: Aggregate LLM-suggested rejections
- `correlate_score_with_exclusions()`: Link exclusions to score improvements
- `generate_recommendations()`: Create prioritized action list with confidence scores

**Algorithm**:
```python
# High confidence = frequent exclusion + repeated rejection recommendation
if exclude_count >= threshold_exclude AND reject_count >= threshold_reject:
    confidence = "high"
elif one of the above is true:
    confidence = "medium"
else:
    skip
```

### 2. Auto Executor (`scripts/auto_clause_iteration.py`)

**Purpose**: Apply recommendations safely with dry-run support.

**Features**:
- Dry-run mode (`-n`): preview without executing
- Confidence thresholding: only apply high-confidence by default
- Operation logging: track what was changed when
- Rollback-ready: JSON logs enable manual revert if needed

**Operations**:
- `clause_review(id, 'rejected')`: Mark clause as rejected (prevents assembly)
- `update_clause(...)`: Modify body/tags (future enhancement)

**Safety gates**:
- Skip if `tag_review` incomplete
- Require `confidence='high'` for auto-apply
- Human review required for medium/low confidence

## Workflow

### Phase 1: Analysis (Manual)
```bash
# After running ~50 pipeline runs
python scripts/analyze_clause_iteration.py --limit 50 --output analysis.json

# Review recommendations
cat analysis.json | jq '.[] | select(.confidence=="high")'
```

### Phase 2: Dry Run (Validation)
```bash
python scripts/auto_clause_iteration.py \
  --analysis analysis.json \
  --confidence high \
  -n  # DRY RUN
```

### Phase 3: Apply (Production)
```bash
python scripts/auto_clause_iteration.py \
  --analysis analysis.json \
  --confidence high \
  --commit-log ops_log.jsonl
```

## Data Flow

### Pipeline Runs Schema
```sql
-- Existing schema supports our needs
CREATE TABLE pipeline_runs (
  id BIGINT PRIMARY KEY,
  contract_type TEXT,
  tags JSONB,
  stance TEXT,
  rubric_name TEXT,
  score REAL,
  all_pass INTEGER,
  iteration INTEGER,
  actions_taken JSONB,  -- [{iteration, excluded_ids, recommendations}]
  recommendations JSONB,  -- [{clause_id, action, reason}]
  created_at TEXT
);
```

### Recommendation Structure
```json
{
  "clause_id": 7123,
  "section": "检验期限",
  "body_preview": "...检验期 14 天内书面通知...",
  "exclude_count": 8,           # how many times excluded across runs
  "reject_count": 5,            # how many times LLM recommended reject
  "reasons": ["thin content", "duplicates base"],
  "confidence": "high",         # based on thresholds
  "type": "reject_clauses"
}
```

## Threshold Strategy

| Confidence | Exclude Count | Reject Count | Action |
|------------|--------------|--------------|--------|
| **high**   | ≥5           | ≥5           | Auto-apply |
| **medium** | 3-4          | 2-4          | Manual review |
| **low**    | <3           | <2           | Ignore |

Configurable via CLI args:
- `--threshold-exclude N`: change exclude count threshold
- `--threshold-reject N`: change reject count threshold
- `--confidence level`: filter by confidence level

## Error Handling

1. **Missing clause**: log warning, skip
2. **Database error**: rollback current transaction, continue with next
3. **Invalid recommendation**: log and skip (fail-safe)
4. **Assembly not ready**: check `is_assembly_ready()` before applying

## Future Enhancements

1. **Body optimization**: Instead of just rejecting, suggest improved body text
2. **Scenario-based filtering**: Only apply to specific business scenarios
3. **A/B testing**: Compare scores before/after applying changes
4. **Web dashboard**: Visualize trends, approve batch operations
5. **Continuous learning**: Run analyzer after every N pipeline runs automatically

## Testing Strategy

1. **Dry-run validation**: Verify no unexpected changes in `-n` mode
2. **Staging DB**: Test on copy of law_bench.db before production
3. **Rollback test**: Ensure logged operations can be reversed
4. **Threshold tuning**: Adjust thresholds based on false positive rate

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Wrongly reject good clauses | Medium confidence requires human approval |
| Over-aggressive updates | Default to exclude-count only, wait for more data |
| Breaking existing workflows | Offline tool, doesn't touch running pipelines |
| No rollback mechanism | Commit logging enables manual revert |

## Success Metrics

- **Precision**: % of applied changes that improve overall score
- **Recall**: % of actually-bad clauses that get flagged
- **Time savings**: Hours saved vs manual review
- **Score impact**: Average eval score delta after applying

---

*Implementation starts with scripts already created; this design formalizes the approach.*
