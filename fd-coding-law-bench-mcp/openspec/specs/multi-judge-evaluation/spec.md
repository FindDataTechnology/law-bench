# multi-judge-evaluation Specification

## Purpose

Execute N judge models in parallel against the same contract and rubric, aggregate verdicts via majority voting with confidence scores, and use confidence to drive pipeline decisions including graceful degradation when judges are unavailable.

## Requirements

### Requirement: Multi-judge evaluation with parallel execution

The system MUST execute N judge models in parallel against the same contract and rubric.

#### Scenario: 3-judge parallel eval
- **WHEN** system invokes `evaluate_contract(contract_text, rubric_name, judge_models=["kimi-k3", "glm-5", "deepseek"])`
- **THEN** all three judges run concurrently via ThreadPoolExecutor (max_workers >= 3)

#### Scenario: Judge per-criterion assignment
- **WHEN** system calls a judge model
- **THEN** each criterion is evaluated independently by that judge using strict_mode=True (binary pass/fail)

### Requirement: Majority vote verdict aggregation

The system MUST aggregate N judges' verdicts into a single consensus verdict per criterion using majority voting.

#### Scenario: Unanimous PASS (3/3)
- **WHEN** all three judges return verdict="pass" for a criterion
- **THEN** aggregated verdict is `pass` with confidence=1.0

#### Scenario: Majority PASS (2/1)
- **WHEN** two judges return verdict="pass" and one returns verdict="fail"
- **THEN** aggregated verdict is `pass` with confidence=0.67

#### Scenario: Majority FAIL (1/2)
- **WHEN** one judge returns verdict="pass" and two return verdict="fail"
- **THEN** aggregated verdict is `fail` with confidence=0.67

#### Scenario: Record per-judge breakdown
- **WHEN** evaluation completes
- **THEN** result includes `per_judge_breakdown`: `{criterion_id: [{model:"kimi-k3", verdict:"pass"}, {model:"glm-5", verdict:"fail"}, ...]}`

### Requirement: Confidence-based pipeline decisions

The system MUST use confidence scores to determine auto-reject aggressiveness.

#### Scenario: High-confidence failures (conf=1.0)
- **WHEN** a criterion fails with unanimous disagreement (3/3 fail)
- **THEN** this is treated as a "critical gap" -- auto-generation prioritized over other actions

#### Scenario: Medium-confidence failures (conf=0.67)
- **WHEN** a criterion fails with majority disagreement (2/3 fail)
- **THEN** this is treated as a "soft gap" -- may or may not trigger auto-reject depending on total failure count

#### Scenario: High-confidence passes (conf=1.0)
- **WHEN** a criterion passes with unanimous agreement (3/3 pass)
- **THEN** this is confirmed "stable" -- no further iterations needed for this criterion

### Requirement: Graceful degradation on judge unavailability

The system MUST handle partial judge availability without crashing the pipeline.

#### Scenario: Only 2 judges available
- **WHEN** one judge API fails (timeout/rate-limit)
- **THEN** pipeline degrades to 2-judge mode with unanimous-required verdicts (2/2 required for pass)

#### Scenario: Only 1 judge available
- **WHEN** only one judge remains operational
- **THEN** pipeline uses single-judge verdicts but marks results as `low_confidence=true` and skips auto-reject

#### Scenario: All judges unavailable
- **WHEN** all judge APIs fail
- **THEN** pipeline halts with clear error message and does NOT attempt fallback

### Requirement: Evaluation scoring function

The `score` field MUST be 1.0 only when ALL criteria pass with at least medium confidence (min confidence >= 0.67); otherwise it SHALL be 0.0.

#### Scenario: All-pass calculation
- **WHEN** evaluating a contract
- **THEN** score = 1.0 if all criteria have aggregated_verdict="pass" AND min(confidence) >= 0.67

#### Scenario: Score breakdown
- **WHEN** evaluation completes
- **THEN** summary includes: `{all_pass: true/false, n_unanimous_pass: X, n_majority_pass: Y, n_failures: Z}`

### Requirement: Per-criterion reasoning output

The `criteria_results[].reasoning` field MUST include a per-judge breakdown showing which judges agreed or disagreed on each verdict.

#### Scenario: Reasoning format
- **WHEN** returning criteria results
- **THEN** each criterion includes:
  ```json
  {
    "id": "ownership_transfer",
    "verdict": "pass",
    "confidence": 0.67,
    "reasoning": "Clause states '所有权自交付时转移', matching rubric guidance.",
    "per_judge_reasoning": {
      "kimi-k3": "Clause explicitly defines ownership transfer timing...",
      "glm-5": "Ownership transfer clause present...",
      "deepseek": "Clear statement of ownership transfer mechanism..."
    }
  }
  ```
