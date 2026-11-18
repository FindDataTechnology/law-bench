## ADDED Requirements

### Requirement: Assembly-Readiness Gating Ignores Metadata Keys
The assembly engine SHALL determine a custom clause's assembly readiness solely from its review dimensions — a clause is assembly-ready when every review dimension carries the value `approved`. Keys prefixed with `_` inside the review state (e.g. `_imported_at`, `_source_hash`, `_note`) are metadata and SHALL NOT be treated as review dimensions for gating, setting, or reporting purposes.

#### Scenario: Metadata key does not block assembly
- **WHEN** a custom clause's review state is `{"stance": "approved", "_note": "auto-approved-pilot"}`
- **THEN** the clause is assembly-ready and participates in override resolution

#### Scenario: Pending genuine dimension still blocks assembly
- **WHEN** a custom clause's review state is `{"stance": "pending", "_imported_at": "2026-08-17T10:00:28"}`
- **THEN** the clause is not assembly-ready

#### Scenario: Bulk review sets only genuine dimensions
- **WHEN** a bulk review operation sets a clause's review status
- **THEN** it updates every genuine review dimension to that status and leaves `_`-prefixed metadata keys untouched
