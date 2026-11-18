## Purpose

Governs how evaluation and draft-generation concurrency is resolved and bounded across the system: one environment default for judge worker pools, opt-in parallelism for compare draft generation, and the rate-limit backoff invariant that must hold under any concurrency level.

## ADDED Requirements

### Requirement: Judge Worker Pool Default Resolution
The judge worker-pool size used when scoring a contract against a rubric SHALL be resolved, for any caller that does not pass an explicit worker count, from the `EVAL_MAX_WORKERS` environment variable. When the variable is unset or not a positive integer, the default SHALL be 8. The resolved value SHALL be clamped to the range [1, 16]; a value above 16 SHALL be clamped to 16. Clamping and fallback SHALL be observable in logs/verbosity output so operators can see the effective worker count.

#### Scenario: Unset variable uses default
- **WHEN** a contract is evaluated with `EVAL_MAX_WORKERS` unset
- **THEN** criteria are judged with a worker pool of 8, identical to the behavior before this change

#### Scenario: Valid override raises parallelism
- **WHEN** `EVAL_MAX_WORKERS=12` is set and a contract is evaluated
- **THEN** criteria are judged with a worker pool of 12

#### Scenario: Out-of-range value is clamped
- **WHEN** `EVAL_MAX_WORKERS=64` is set
- **THEN** the worker pool is clamped to 16 and the effective value 16 is reported

#### Scenario: Invalid value falls back to default
- **WHEN** `EVAL_MAX_WORKERS=abc` is set
- **THEN** the worker pool falls back to 8 and the fallback is reported

### Requirement: Rate-Limit Backoff Invariant
Every judge call SHALL retain per-call retry on rate-limit and transient relay errors (429, ServiceUnavailable, 503) with escalating backoff across at least 3 attempts, regardless of the worker-pool size in use. A rate-limited call SHALL never be recorded as a criterion failure; a judge call that errors after retries SHALL mark only its own criterion as errored, not the run.

#### Scenario: Backoff holds at elevated concurrency
- **WHEN** criteria are judged with a worker pool of 16 and the relay returns 429 for some calls
- **THEN** each rate-limited call retries with escalating backoff before retry exhaustion
- **AND** no criterion is recorded as failed solely because of a rate-limit error

#### Scenario: One exhausted call does not sink the run
- **WHEN** a single judge call errors after all retry attempts
- **THEN** only that criterion carries the error; the remaining criteria keep their verdicts

### Requirement: Parallel Compare Draft Generation
A compare run SHALL accept a `concurrency` parameter bounding the number of drafts generated simultaneously across the prompt × draft matrix, defaulting to 1 (sequential, identical to prior behavior). The value SHALL be clamped to [1, 8]. Regardless of concurrency, the persisted evaluation rows SHALL appear in the same deterministic order as the sequential path (prompt-major, draft-minor), and each draft SHALL keep its own prompt/draft identity in storage.

#### Scenario: Sequential default preserves behavior
- **WHEN** a compare runs without an explicit concurrency value
- **THEN** drafts are generated one at a time and all stored results match a pre-change run of the same inputs

#### Scenario: Parallel generation with bounded concurrency
- **WHEN** a compare of 3 prompts × 3 drafts runs with concurrency 4
- **THEN** drafts are generated with at most 4 in flight simultaneously
- **AND** 9 evaluation rows are persisted under the compare, ordered prompt-major then draft-minor, each carrying its own `prompt_name` and draft text

#### Scenario: Oversized concurrency is clamped
- **WHEN** a compare is requested with concurrency 20
- **THEN** the effective concurrency is 8 and the effective value is reported to the caller
