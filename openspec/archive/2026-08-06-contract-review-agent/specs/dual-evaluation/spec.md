## ADDED Requirements

### Requirement: Rubric-based evaluation (existing)
The system SHALL evaluate the final contract using the existing rubric-based evaluation (`src.eval.scoring.evaluate_contract()`). This SHALL load the rubric criteria from the database, create a `GEval(strict_mode=True)` metric per criterion, run all criteria concurrently, and return per-criterion PASS/FAIL verdicts with reasoning.

#### Scenario: Evaluate contract against sale rubric
- **WHEN** the final contract is evaluated against `contract_sale_v1` rubric
- **THEN** the system SHALL load all criteria for that rubric
- **THEN** each criterion SHALL be evaluated as PASS or FAIL
- **THEN** the result SHALL include `n_passed`, `n_criteria`, `all_pass`, and per-criterion verdicts

### Requirement: Deepeval metrics evaluation
The system SHALL evaluate the final contract using deepeval metrics in addition to the rubric eval. The metrics SHALL include: `HallucinationMetric` (did the filler invent terms not in templates?), `FaithfulnessMetric` (does the contract stay faithful to clause bodies?), and a custom `GEval("Slot Relevance")` (are filled values contextually appropriate?).

#### Scenario: Hallucination detection
- **WHEN** the filled contract contains terms not present in any clause template
- **THEN** the `HallucinationMetric` SHALL flag these as hallucinations
- **THEN** the score SHALL reflect the ratio of hallucinated claims to total claims

#### Scenario: Slot relevance evaluation
- **WHEN** the slot `penalty_rate` is filled with "0.05" for a sale contract
- **THEN** the `GEval("Slot Relevance")` metric SHALL evaluate whether this value is contextually appropriate for a sale contract
- **THEN** the metric SHALL return a score between 0 and 1 with reasoning

### Requirement: Combined evaluation results
The system SHALL merge rubric eval results and deepeval metric results into a unified evaluation report. The report SHALL include: rubric score (n_passed/n_criteria), deepeval metric scores (hallucination, faithfulness, slot_relevance), and an overall pass/fail status.

#### Scenario: Combined report shows both eval types
- **WHEN** the evaluation node completes
- **THEN** the result SHALL include `eval_result` (rubric) and `deepeval_scores` (metrics)
- **THEN** the frontend SHALL display both in the metrics panel

### Requirement: Evaluation timing and model tracking
Each evaluation run SHALL track the time taken, the judge model used, and the token consumption. This data SHALL be included in the `agent_runs` table.

#### Scenario: Evaluation metrics recorded
- **WHEN** the evaluation node completes
- **THEN** the result SHALL include `eval_duration` (seconds), `judge_model` (string), and `eval_tokens` (int)
- **THEN** these values SHALL be stored in the `agent_runs.model_calls` JSONB column
