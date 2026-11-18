# law-catalog Specification

## Purpose

Holds a read-only replica of the external 法规库 catalog (law_db.laws) inside law-bench's own PostgreSQL, and resolves the free-text law names cited by contract clauses (`《...》` strings) to canonical catalog entries — the foundation every contract↔law link builds on.

## Requirements

### Requirement: Catalog replica import

The system SHALL import the law catalog export (columns: id, title, category, publish, expiry, status, src_db, content_status) produced from the 法规库 PostgreSQL into a dedicated schema in law-bench's main PostgreSQL. Import SHALL be idempotent: re-running against a newer export replaces the replica content without manual cleanup and without leaving stale rows.

#### Scenario: Initial import

- **WHEN** an operator runs the import with a catalog export file containing 21,746 law rows
- **THEN** the replica contains one row per export row with matching id, title, category, publish, expiry, status, src_db, content_status
- **AND** the import reports row counts for verification

#### Scenario: Refresh after new laws land in 法规库

- **WHEN** the 法规库 ingests an flk (新法速递) increment and the operator re-exports and re-runs the import
- **THEN** the replica reflects the new export exactly, with no rows from the previous load remaining that are absent from the new export

#### Scenario: Replica serves lookups without external services

- **WHEN** any component queries the replica while the 法规库's own PostgreSQL, Qdrant, and embedding services are unreachable
- **THEN** lookups against the replica still succeed, because the replica is a local copy with no runtime dependency on those services

### Requirement: Name resolution to catalog entries

The system SHALL resolve law name strings (as they appear in clause `law_refs`, e.g. `中华人民共和国民法典`, `合同法`, `九民纪要`) to replica catalog entries, using a fixed resolution ladder: normalization (strip the `中华人民共和国` prefix, consistent with the existing `_dedup_key` convention) → curated alias table (简称/旧称 → 全称) → trigram similarity match above a configured threshold. Every resolution result SHALL record how it matched (`resolved_via`: exact / alias / trigram / unresolved). Resolution SHALL be deterministic: identical inputs produce identical results across runs.

#### Scenario: Normalized exact match

- **WHEN** a clause cites `《中华人民共和国民法典》` and the replica title is `中华人民共和国民法典`
- **THEN** the name resolves to that catalog entry with `resolved_via = exact`

#### Scenario: Alias match for a common shorthand

- **WHEN** a clause cites `《九民纪要》` and the alias table maps it to `全国法院民商事审判工作会议纪要`
- **THEN** the name resolves to that catalog entry with `resolved_via = alias`

#### Scenario: Fuzzy match above threshold

- **WHEN** a clause cites a name that differs from the replica title only by an edition/revision suffix and trigram similarity exceeds the configured threshold
- **THEN** the name resolves to the best-matching entry with `resolved_via = trigram`

#### Scenario: No match lands in the review queue

- **WHEN** a cited name has no normalized, alias, or above-threshold trigram match
- **THEN** the resolution records `resolved_via = unresolved`
- **AND** the name appears in the human review queue so an operator can add an alias or record a deliberate non-match

### Requirement: Clause-to-law resolution results stored separately from derived law_refs

The system SHALL store resolution results in a dedicated table keyed by clause and law (clause_id, law_id, status snapshot, resolved_via), populated by an independently re-runnable resolution pass. The pass SHALL NOT modify the `clauses.law_refs` derived column, clause bodies, or the body→law_refs derivation pipeline: editing a clause and re-deriving law_refs SHALL never destroy or require rebuilding resolution results by side effect, and re-running the pass after such an edit SHALL recompute results from the current law_refs.

#### Scenario: Re-run after a clause is edited

- **WHEN** a clause body is edited (law_refs re-derived from the new body) and the resolution pass re-runs
- **THEN** the resolution results for that clause match its current law_refs
- **AND** results for untouched clauses are unchanged

#### Scenario: Derivation pipeline untouched

- **WHEN** the resolution pass runs
- **THEN** every clause's `law_refs` value is byte-identical to before the pass

### Requirement: Expiry column excluded from validity judgments

The system SHALL NOT use the catalog's `expiry` column in any validity, liveness, or staleness judgment. Its real-world semantics is 施行日期 (effective date), not an expiry date: laws with `expiry` in the past and `status = 有效` are common and current. Validity classification SHALL come from the `status` column only.

#### Scenario: Past expiry does not flag a valid law

- **WHEN** a catalog row has `publish = 1999-03-15`, `expiry = 1999-10-01`, `status = 有效`
- **THEN** no component of this capability classifies that law as repealed, expired, or stale
