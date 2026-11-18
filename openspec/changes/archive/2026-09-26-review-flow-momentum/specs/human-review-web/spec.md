## ADDED Requirements

### Requirement: Decision Flow Continuation

After a successful decision POST, the system SHALL redirect the annotator to their next pending task in the same batch (slot-ordered), rather than the batch list. When no pending task remains for that annotator in the batch, the system SHALL redirect to the batch list with a flash message reporting the batch's completion state. Conflict (task already decided by someone else) behavior is unchanged: redirect back to the same task with the existing conflict flash.

#### Scenario: Next task exists

- **WHEN** the annotator submits a valid decision for task 5 and task 9 is their next pending task in the same batch
- **THEN** the response SHALL be a 303 redirect to `/review/9`
- **AND** the page SHALL show a success flash confirming the previous decision was recorded

#### Scenario: Queue drained

- **WHEN** the annotator submits a valid decision and no pending task remains for them in that batch
- **THEN** the response SHALL be a 303 redirect to `/review?batch=<batch_id>` with a flash stating the batch queue is done for them

#### Scenario: Conflict path unchanged

- **WHEN** two annotators decide the same task and the second submit loses the race
- **THEN** the second annotator SHALL be redirected back to that task with the existing conflict flash, and the next-task lookup SHALL NOT have consumed or altered any task state

### Requirement: Queue Position Indicator

The task page SHALL display, for a pending task, the annotator's position within their own pending queue for the batch, in the form「第 k / n 条待判」 where n is the count of that annotator's pending tasks in the batch and k is 1-based. For a task already decided (review revisit), the indicator SHALL be omitted.

#### Scenario: Position shown on a pending task

- **WHEN** an annotator with 11 pending tasks in batch `v4-validity-01` opens their 3rd pending task
- **THEN** the page SHALL show「第 3 / 11 条待判」

#### Scenario: Indicator omitted on decided tasks

- **WHEN** anyone opens a task whose status is `decided`
- **THEN** the page SHALL NOT render the queue position indicator

### Requirement: Keyboard Verdict Selection

The decision form SHALL support number-key selection: pressing `1`..`n` selects the 1st..nth verdict radio in rendered order. The mapping SHALL be surfaced as a hint on each verdict label (e.g.「按 1」). Number keys SHALL only select — never auto-submit; submission remains an explicit action (button or Enter). The listener SHALL ignore keystrokes typed into the note textarea or when a modifier key is held.

#### Scenario: Number key selects a verdict

- **WHEN** the annotator presses `2` outside any text field on a pending validity task with verdicts (pass, fail)
- **THEN** the fail radio becomes selected and the form is not submitted

#### Scenario: Typing a note is unaffected

- **WHEN** the annotator types `1` while focused on the note textarea
- **THEN** the character SHALL be entered as text and no radio selection SHALL change

### Requirement: Primary Submit Affordance

The decision submit button SHALL render as the system's primary button style (`btn-primary`), and the irreversibility note SHALL remain adjacent to it.

#### Scenario: Submit reads as the primary irreversible action

- **WHEN** an annotator with the `review:annotate` scope opens a pending task
- **THEN** the submit control SHALL carry `btn-primary` styling
- **AND** the「提交后记录你的登录身份，不可修改」note SHALL remain visible next to it
