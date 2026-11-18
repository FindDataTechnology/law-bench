# Implementation Tasks

## Task 1: Create analyzer script
**Status**: ✅ Done
**File**: `scripts/analyze_clause_iteration.py`

- [x] Read pipeline_runs table
- [x] Extract actions_taken.excluded_ids
- [x] Aggregate recommendations with action='reject'
- [x] Compute confidence scores (high/medium/low)
- [x] Output JSON recommendations
- [x] CLI args: --limit, --threshold-exclude, --threshold-reject, --output

## Task 2: Create auto-executor script
**Status**: ✅ Done
**File**: `scripts/auto_clause_iteration.py`

- [x] Load analysis JSON
- [x] Dry-run mode (-n flag)
- [x] Confidence thresholding (--confidence high/medium/low)
- [x] Apply clause_review(id, 'rejected') for high-confidence
- [x] Operation logging (--commit-log)
- [x] Safety gates: skip if tag_review incomplete

## Task 3: Test analyzer with real data
**Status**: ✅ Done
**File**: Manual testing

- [x] Run `python scripts/analyze_clause_iteration.py --limit 50 --output test_analysis.json`
- [x] Verify output JSON structure
- [x] Check confidence scores match thresholds
- [x] Review top recommendations for reasonableness

## Task 4: Test auto-executor dry-run
**Status**: ✅ Done
**File**: Manual testing

- [x] Run `python scripts/auto_clause_iteration.py --analysis test_analysis.json -n`
- [x] Verify no database changes in dry-run
- [x] Check output shows planned operations
- [x] Test with different confidence thresholds

## Task 5: Apply changes to production
**Status**: ⏳ Pending
**File**: Manual operation

- [ ] Run analyzer on full dataset (limit=100+)
- [ ] Review high-confidence recommendations
- [ ] Execute auto-executor with --confidence high
- [ ] Verify clause_review updates applied
- [ ] Run pipeline again to measure score improvement

## Task 6: Document workflow
**Status**: ✅ Done
**File**: `docs/clause-iteration-workflow.md`

- [x] Write usage guide for analyzer
- [x] Document auto-executor safety procedures
- [x] Include example commands and expected output
- [x] Add troubleshooting section

## Task 7: Integrate with pipeline (optional)
**Status**: 📋 Backlog
**File**: `src/pipeline/improve.py`

- [ ] Add post-pipeline hook to auto-run analyzer
- [ ] Store recommendations in separate table for tracking
- [ ] Add MCP tool to trigger analyzer from dashboard
- [ ] Implement continuous learning loop

## Dependencies
- Task 3 depends on Task 1
- Task 4 depends on Task 2
- Task 5 depends on Tasks 3 and 4
- Task 6 can run in parallel with Task 5
- Task 7 is future work, blocked by Task 5 success

## Acceptance Criteria
1. Analyzer correctly identifies frequently-excluded clauses
2. Auto-executor applies changes safely with dry-run
3. High-confidence recommendations improve eval scores
4. No breaking changes to existing pipeline
5. Documentation complete for manual operation
