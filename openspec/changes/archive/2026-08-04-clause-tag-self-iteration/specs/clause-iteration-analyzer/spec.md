## ADDED Requirements

### Requirement: Analyzer reads pipeline_runs table
The system SHALL read historical pipeline_runs to extract clause exclusion patterns and LLM recommendations.

#### Scenario: Analyze 50 recent runs
- **WHEN** analyzer is invoked with `--limit 50`
- **THEN** system reads last 50 pipeline_runs rows and extracts `actions_taken` and `recommendations` JSONB fields

### Requirement: Count clause exclusion frequency
The system SHALL count how many times each custom clause_id appears in `actions_taken.excluded_ids` across all analyzed runs.

#### Scenario: Clause excluded 8 times
- **WHEN** clause_id=7123 appears in 8 different pipeline runs' excluded_ids
- **THEN** analyzer reports `exclude_count: 8` for that clause

### Requirement: Aggregate LLM rejection recommendations
The system SHALL aggregate `recommendations` where `action='reject'` and count occurrences per clause_id.

#### Scenario: 5 reject recommendations
- **WHEN** LLM recommended reject for clause_id=7123 in 5 runs
- **THEN** analyzer reports `reject_count: 5` with top 3 reasons

### Requirement: Compute confidence score
The system SHALL assign confidence based on exclusion and rejection counts using configurable thresholds.

#### Scenario: High confidence clause
- **WHEN** exclude_count >= 5 AND reject_count >= 5
- **THEN** confidence is set to "high"

#### Scenario: Medium confidence clause
- **WHEN** exclude_count >= 3 OR reject_count >= 3
- **THEN** confidence is set to "medium"

### Requirement: Output JSON recommendations
The system SHALL output a JSON array of recommendations sorted by confidence and count.

#### Scenario: Generate analysis.json
- **WHEN** analyzer completes with `--output analysis.json`
- **THEN** file contains sorted recommendations with clause_id, section, body_preview, exclude_count, reject_count, confidence, reasons

### Requirement: Correlate score with exclusions
The system SHALL compute average eval score and all-pass rate across analyzed runs.

#### Scenario: Report score trends
- **WHEN** analyzer processes 50 runs
- **THEN** output includes avg_score, all_pass_rate, and per-run breakdown of score vs exclusion count
