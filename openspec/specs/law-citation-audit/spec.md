# law-citation-audit Specification

## Purpose

Audits every law citation in the clause corpus against the law catalog replica, classifying citations by the cited law's status (repealed / amended / unresolvable) and surfacing the result as a report plus a human review queue — report-only, never mutating clauses.

## Requirements

### Requirement: Corpus-wide citation audit with status classification

The system SHALL audit all clauses' law citations (via the law-catalog resolution layer) and classify each resolved citation by the cited law's catalog `status`: citations of laws with status `已废止` or `失效` SHALL be classified as "引用已废法律" (repealed); status `已修改` SHALL be classified separately as "已修改（多数仍有效，仅被修正）"; citations whose resolution is `unresolved` (including laws whose catalog status is NULL or a dirty value) SHALL be classified into a fallback list for title-normalization or manual disposition. Classification SHALL depend only on the `status` column, never on `expiry` (施行日期).

#### Scenario: Clause citing a repealed law is flagged

- **WHEN** a clause cites `《中华人民共和国合同法》` and the catalog replica has that law with `status = 已废止`
- **THEN** the audit flags the citation as 引用已废法律 and lists the clause and the law

#### Scenario: Amended laws are a separate category

- **WHEN** a clause cites a law with `status = 已修改`
- **THEN** the audit lists it under the 已修改 category, distinct from the repealed category

#### Scenario: Unresolved citations land in the fallback list

- **WHEN** a clause cites a name with `resolved_via = unresolved`, or resolves to a catalog row whose status is NULL or a dirty value (e.g. `sxx:3`)
- **THEN** the audit places that citation in the fallback list for manual disposition

### Requirement: Audit report output

The system SHALL produce an audit report (markdown, committed to the repo) summarizing total citations, resolution coverage, and the three classification categories, with per-clause detail (contract type, clause id/section, cited name, resolved law title, status, resolved_via). The report generation SHALL be repeatable and deterministic for a fixed corpus and catalog snapshot.

#### Scenario: Generate the audit report

- **WHEN** an operator runs the audit over the clause corpus
- **THEN** a markdown report is written containing the summary counts and per-clause findings in all three categories

#### Scenario: Report reflects a refreshed catalog

- **WHEN** the catalog replica is refreshed (e.g. a law's status changed) and the audit re-runs
- **THEN** the new report reflects the updated statuses

### Requirement: Review queue for audit findings

The system SHALL expose the audit findings (unresolved names and disputed classifications) as a web review queue where an operator can act on each item: confirm the suggested resolution (which may add an alias), mark it a deliberate non-match, or leave it pending. Review actions SHALL affect future resolution runs (e.g. a confirmed alias is used by the next pass) but SHALL NOT edit clause bodies or `law_refs`.

#### Scenario: Operator confirms an alias from the queue

- **WHEN** an operator confirms that an unresolved name maps to a specific catalog law
- **THEN** the alias is recorded and the next resolution pass resolves that name with `resolved_via = alias`

#### Scenario: Audit and review never mutate clauses

- **WHEN** the audit runs and any review action is taken
- **THEN** clause bodies and `law_refs` values are unchanged

### Requirement: Re-runnable audit

The audit SHALL be re-runnable at any time over the current corpus and catalog snapshot without special preparation, and consecutive runs over unchanged inputs SHALL produce identical findings.

#### Scenario: Consecutive runs agree

- **WHEN** the audit runs twice with no corpus or catalog changes in between
- **THEN** both reports contain identical findings and counts
