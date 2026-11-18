# law-citation-remediation Specification

## Purpose

Deterministically repairs repealed-law citations in clause bodies (《合同法》→《民法典》 class substitutions) through the canonical clause-update path, recording every change as a machine-verifiable evidence chain with batch snapshots for rollback — and exposing the records for paper statistics, human review, and finetune-data extraction.

## Requirements

### Requirement: Successor mapping with authority evidence

The system SHALL maintain a successor mapping (死法 → 承继法) in the law_catalog schema. Each entry SHALL carry: the dead law_id, the successor law_id, the repealing authority (废止决定/施行法的 law_id 引用, where the catalog provides one), the effective date, and a rule version. Entries whose successor requires human confirmation (local regulations) SHALL be represented as placeholders that never auto-apply.

#### Scenario: Civil Code succession entry

- **WHEN** the mapping is seeded for 中华人民共和国合同法
- **THEN** it points to the catalog's 民法典 entry with an authority reference and effective date 2021-01-01

#### Scenario: Local repealed regulation stays a placeholder

- **WHEN** a dead local regulation has no confirmed successor
- **THEN** the mapping entry is flagged as requiring human disposition and no automated application ever uses it

### Requirement: Dry-run gate with diff and reason per clause

Before any application, the system SHALL produce a dry-run report listing, per clause: the exact before/after citation text (full body diff), the mapping entry applied, and the evidence chain (dead law status, successor law status). The application step SHALL NOT run until this report has been reviewed; replacement patterns that match historical narration (e.g. "合同法实施以来") SHALL be excluded by whitelist rules or surfaced as skipped-for-review.

#### Scenario: Dry-run report contents

- **WHEN** a dry-run runs over the 298 repealed citations
- **THEN** every applicable clause appears with before/after text and its mapping's evidence chain
- **AND** non-applicable matches (narration, ambiguous) are listed separately as skipped

### Requirement: Application through the canonical update path only

All clause modifications SHALL go through the existing `update_clause` store function (re-derives `law_refs`/`body_hash`, sets `manual=true`). No direct SQL writes to clause bodies. The `manual=true` side effect (re-extraction preserves remediated clauses) is accepted and documented.

#### Scenario: Applied clause re-derives its citations

- **WHEN** a clause body's 《合同法》 reference is replaced via the remediation apply step
- **THEN** the clause's `law_refs` re-derives to the successor law name and the row carries `manual=true`

#### Scenario: No second write path

- **WHEN** the remediation applies, rolls back, or records
- **THEN** clause rows are only ever mutated through the canonical store functions

### Requirement: Revision records as queryable evidence chains

Every applied (or reviewed-no-action) disposition SHALL be recorded in a law_catalog revision table with: clause_id, batch name, citation before/after strings, dead law_id, successor law_id, authority law_id, rule version, git sha of the driving code, applied_at, and disposition (applied / skipped-review / reviewed-no-action). The table SHALL be idempotent per (clause_id, batch) and joinable with the catalog and clause tables. Simultaneously, each batch SHALL write file snapshots under `output/remediation/<batch>/` (manifest with git sha, before/ full-row, applied/ records) for rollback. No clause row is ever deleted.

#### Scenario: Record is replayable evidence

- **WHEN** a revision record is inspected later
- **THEN** the dead law's repealed status and the successor's validity are verifiable by joining the recorded law_ids against the catalog replica

#### Scenario: Reviewed-no-action for amended laws

- **WHEN** the 17 已修改 citations are processed
- **THEN** each is recorded with disposition reviewed-no-action and no clause body changes

### Requirement: Closed-loop verification and rollback

After application, re-running the name-level resolution and audit SHALL be the acceptance check: the repealed category SHALL drop to the count of unmapped local cases (≈7). A rollback operation SHALL restore any batch's (or single clause's) bodies from the before snapshots through the canonical update path and mark the revision records rolled-back. Consecutive re-application of the same batch SHALL be a no-op.

#### Scenario: Post-apply verification

- **WHEN** application completes and the audit re-runs
- **THEN** the repealed citation count equals the unmapped placeholder count and every applied clause resolves to a 有效-status law

#### Scenario: Batch rollback restores original bodies

- **WHEN** a batch is rolled back
- **THEN** affected clause bodies match their before snapshots and the audit's repealed count returns to the pre-batch value

### Requirement: Consumption exports

The revision records SHALL be exportable for three consumers: (a) paper statistics — aggregate SQL/JSONL of counts by disposition/contract_type/citation, plus before/after audit summary numbers; (b) human review — a web page listing revisions with before/after diff and evidence chain, under the existing /law-catalog/ route family, read-only; (c) finetune data — before→after correction pairs in the repo's existing finetune-data conventions, including the reason as context.

#### Scenario: Finetune pair export

- **WHEN** finetune export runs for a batch
- **THEN** each applied revision yields a pair containing the original body citation span, the corrected span, and the evidence-chain reason
