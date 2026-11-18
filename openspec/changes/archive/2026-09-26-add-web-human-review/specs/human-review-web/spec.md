## ADDED Requirements

### Requirement: Review Task Storage

The system SHALL store human-review tasks in a `review_tasks` table. Each row represents one annotation slot: `batch_id` (operator-chosen batch identifier), `batch_type` (`validity` or `gold_curation`), `eval_criteria_result_id` (referencing `eval_criteria_results` with `ON DELETE CASCADE`), `slot` (1-based annotator slot), `status` (`pending` or `decided`), `annotator_verdict` (`pass`/`fail` for validity batches, `approved`/`rejected`/`skipped` for gold curation batches), `annotator` (the authenticated identity that decided), `note`, `reviewed_at`, and `created_at`. Batch creation SHALL be idempotent: re-running with the same `batch_id` SHALL NOT duplicate tasks.

#### Scenario: Batch creation is idempotent

- **WHEN** the sampling script runs twice with the same `batch_id`
- **THEN** the second run creates no new rows and leaves existing decisions unchanged
- **AND** the run reports the number of tasks that already existed

#### Scenario: Deleting the source run removes its tasks

- **WHEN** an `eval_runs` row referenced by review tasks is deleted
- **THEN** the dependent `review_tasks` rows are removed by cascade

### Requirement: Task Detail Composition

For each task the system SHALL expose, via joins, the material an annotator needs: the draft text (`eval_runs.draft_text`), the criterion display name and its human-authored PASS/FAIL guidance (`criteria.title`-equivalent `name`/`description`/`guidance`), the rubric name, and the contract type derived from the rubric name. For `gold_curation` tasks the model verdict and reasoning SHALL additionally be exposed. A task whose joined data cannot be found SHALL surface a clear not-found state.

#### Scenario: Task detail carries the full context

- **WHEN** an annotator opens a task whose `eval_criteria_result_id` joins cleanly
- **THEN** the page shows the draft text, the criterion guidance, and the batch type
- **AND** for `gold_curation` it also shows the model verdict and reasoning

#### Scenario: Dangling reference is a not-found, not a crash

- **WHEN** a task's source rows no longer join (e.g. criteria renamed away)
- **THEN** the page renders a clear not-found state

### Requirement: Blind Annotation for Validity Batches

For `validity` batches the decision page SHALL NOT display the model verdict or model reasoning before the annotator submits. The annotator records their own verdict (`pass`/`fail`) and an optional note. The stored verdict is the annotator's, never copied from the model's.

#### Scenario: Blind form hides the model judgment

- **WHEN** an annotator opens a `validity` task's decision page
- **THEN** the page does not contain the model verdict or reasoning in any form

#### Scenario: Own verdict is recorded

- **WHEN** the annotator submits `fail` with a note
- **THEN** the task becomes `decided` with `annotator_verdict='fail'`, the note, and their identity

### Requirement: Concurrent Decision Safety

A decision SHALL apply only while the task is `pending`. The decision update SHALL be conditional (`UPDATE ... WHERE status='pending'`); when two annotators decide the same slot, exactly one succeeds and the other receives a conflict response that leaves the row unchanged.

#### Scenario: Second submit on the same slot conflicts

- **WHEN** annotator B submits after annotator A's decision on the same task row
- **THEN** B sees a conflict message and the task still shows A's decision

#### Scenario: One annotator cannot claim both slots of an item

- **WHEN** a multi-slot item has one slot already decided by annotator A
- **THEN** A's queue no longer offers that item's remaining slots
- **AND** other annotators still see them as pending

### Requirement: Annotator Identity and Provenance

`annotator` SHALL be taken from the authenticated web session identity. It SHALL NOT be a free-text form field. Every decided task SHALL record `reviewed_at`. Exports SHALL stamp reviewer provenance from these fields (human reviewer identity, not a typed string).

#### Scenario: Identity comes from the session

- **WHEN** a logged-in annotator submits a decision
- **THEN** the stored `annotator` equals the session identity without any form input

### Requirement: Review Page Access Control

Review pages SHALL require an authenticated session. The task list and detail pages SHALL be visible to any authenticated user; decision submission SHALL require the `review:annotate` scope. Unauthenticated access SHALL redirect to login; authenticated users without the scope SHALL get 403 on decision submission.

#### Scenario: Anonymous visitor is redirected

- **WHEN** an unauthenticated visitor opens `/review`
- **THEN** they are redirected to the login flow

#### Scenario: Viewer cannot decide

- **WHEN** an authenticated user whose scopes lack `review:annotate` posts a decision
- **THEN** the response is 403 and the task stays `pending`

### Requirement: Agreement Statistics and Gold Export

The export script SHALL compute and report: per-annotator decision counts; pairwise annotator agreement (and Cohen's kappa where two annotators decided the same `eval_criteria_result_id` within a batch); and human-vs-judge agreement (annotator verdict against the model verdict, per batch and overall). It SHALL flag any annotator whose agreement with the judge is at or above a configurable warning threshold as a possible machine-mediated contamination signal. It SHALL export gold quadruples (`clause_text`, `legal_base`, `verdict`, `reasoning`) composed from the joined data for `gold_curation` tasks decided `approved`, stamped with reviewer provenance.

#### Scenario: Kappa is computed for double-annotated items

- **WHEN** a batch has items decided by two annotators each
- **THEN** the report includes the annotator-pair agreement rate and Cohen's kappa

#### Scenario: Suspiciously high judge agreement is flagged

- **WHEN** an annotator's verdicts match the model's on every item of a batch
- **THEN** the export report flags that annotator with the contamination warning

#### Scenario: Exported gold carries provenance

- **WHEN** approved gold-curation tasks are exported
- **THEN** each exported record carries reviewer identity and a provenance reference back to the review task and source rows

#### Scenario: A record without a legal basis never reaches the gold file

- **WHEN** an approved gold-curation task's joined data carries no law reference (so `legal_base` and `reasoning.citation` would be empty)
- **THEN** the export validates the composed record with the downstream `validate_quadruple` gate and writes it to a worklist file beside the gold file, reporting the reason
- **AND** the gold file is not created empty, so a gold file that exists is always one the downstream flow accepts
