## MODIFIED Requirements

### Requirement: Sync Batch Generation
The system SHALL expose `POST /api/contracts/{contract_type}/generate-batch` (mode D) that generates the contract across the requested (or enumerated) tag combinations in parallel with throttling and returns a sync JSON body `{results, success_count, failure_count}` plus per-item file URLs. The request's `max_concurrent` field (default 5, clamped to [1, 16]) SHALL bound the assembly parallelism; results SHALL be returned in the same order as the requested/enumerated combinations, and per-combo failures SHALL be reported in that item's `error` so one bad combo does not sink the batch. It SHALL return 404 for an unknown contract type.

#### Scenario: Batch generate explicit combos
- **WHEN** a client `POST /api/contracts/sale/generate-batch` with `tag_combinations=[{"stance":"balanced"}]`
- **THEN** the response is `200` with `success_count >= 1` and each result carrying a `docx_url`/`pdf_url`

#### Scenario: Batch honors the concurrency field
- **WHEN** a client `POST /api/contracts/sale/generate-batch` with 6 valid tag combinations and `max_concurrent: 3`
- **THEN** assemblies run with at most 3 in flight simultaneously
- **AND** the `results` array is ordered identically to the submitted `tag_combinations`

#### Scenario: One failing combo does not sink the batch
- **WHEN** a batch of 4 combos includes one that fails the coherence gate
- **THEN** the response is `200` with `success_count: 3`, `failure_count: 1`, and the failing item carries its `error`

#### Scenario: Oversized concurrency is clamped
- **WHEN** a batch is submitted with `max_concurrent: 64`
- **THEN** assembly runs with effective concurrency 16

#### Scenario: Unknown type returns 404
- **WHEN** a client `POST /api/contracts/does_not_exist/generate-batch`
- **THEN** the response status is 404
