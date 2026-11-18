# auto-executor Specification

## Purpose
Apply clause-review recommendations to assembled contracts in a controlled pipeline: load an analysis JSON, dry-run or commit edits behind a confidence threshold, log every operation, and verify the result is assembly-ready.

## Requirements
### Requirement: Load analysis JSON
The system SHALL load recommendations from a JSON file produced by the analyzer.

#### Scenario: Load analysis.json
- **WHEN** executor invoked with `--analysis analysis.json`
- **THEN** system reads JSON array of recommendations

### Requirement: Dry-run mode
The system SHALL support dry-run mode that previews changes without executing.

#### Scenario: Preview without applying
- **WHEN** executor invoked with `-n` or `--dry-run`
- **THEN** system prints what would be changed but does not modify clauses table

### Requirement: Confidence threshold filtering
The system SHALL only apply recommendations meeting the specified confidence threshold.

#### Scenario: Apply high confidence only
- **WHEN** executor invoked with `--confidence high`
- **THEN** only recommendations with confidence="high" are applied; medium/low are skipped

### Requirement: Apply clause_review rejection
The system SHALL call `bulk_review(clause_id, 'rejected')` for reject recommendations.

#### Scenario: Reject a clause
- **WHEN** recommendation has type="reject_clauses" and clause_id=7123
- **THEN** system calls `bulk_review(7123, 'rejected')` which sets all tag_review dims to "rejected"

### Requirement: Operation logging
The system SHALL log all operations to a JSONL file when `--commit-log` is specified.

#### Scenario: Log applied changes
- **WHEN** executor applies 3 changes with `--commit-log ops.jsonl`
- **THEN** ops.jsonl contains 3 JSON lines with timestamp, clause_id, action, success status

### Requirement: Assembly-ready check
The system SHALL skip clauses that are not assembly-ready before applying changes.

#### Scenario: Skip non-ready clause
- **WHEN** clause has tag_review with any dim != "approved"
- **THEN** system logs warning and skips that clause

### Requirement: Error handling and rollback
The system SHALL catch database errors per-clause and continue with remaining recommendations.

#### Scenario: Partial failure
- **WHEN** applying clause 7123 fails with DB error
- **THEN** system logs error, increments failed count, continues with next clause

### Requirement: Summary report
The system SHALL print a summary of total/success/failed/skipped counts after execution.

#### Scenario: Print results
- **WHEN** executor completes
- **THEN** output shows "Total: 10, Success: 8, Failed: 1, Skipped: 1"
