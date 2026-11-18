## ADDED Requirements

### Requirement: Industry Standard Reference Table
The system SHALL maintain an industry standard reference table that maps each unnamed contract type to its governing statutes, industry standards, and core mandatory clauses. The reference table SHALL be stored in the database and updated through a controlled process.

#### Scenario: Create a reference entry for a new unnamed contract type
- **WHEN** a new unnamed contract type is added to the system
- **THEN** the system SHALL create a reference entry with governing statutes, industry standards, and core mandatory clauses
- **AND** store the entry in the industry_standard_references table

#### Scenario: Update a reference entry
- **WHEN** governing statutes or industry standards change for an unnamed contract type
- **THEN** the system SHALL update the reference entry
- **AND** preserve the history of changes for audit purposes

#### Scenario: Query reference entries by contract type
- **WHEN** a user queries the reference entry for a specific contract type
- **THEN** the system SHALL return the governing statutes, industry standards, and core mandatory clauses
- **AND** provide links to the full text of the referenced statutes

### Requirement: Governing Statute Mapping
The system SHALL map each unnamed contract type to its primary governing statutes beyond the Civil Code. The mapping SHALL be based on legal research and expert review.

#### Scenario: Map company_formation to Company Law
- **WHEN** the company_formation contract type is evaluated
- **THEN** the system SHALL reference the Company Law of the PRC (2023 Revision) as the primary governing statute
- **AND** apply criteria derived from Company Law mandatory provisions

#### Scenario: Map employment to Labor Contract Law
- **WHEN** the employment contract type is evaluated
- **THEN** the system SHALL reference the Labor Contract Law of the PRC (2012 Revision) as the primary governing statute
- **AND** apply criteria derived from Labor Contract Law mandatory provisions

#### Scenario: Map insurance to Insurance Law
- **WHEN** the insurance contract type is evaluated
- **THEN** the system SHALL reference the Insurance Law of the PRC (2015 Revision) as the primary governing statute
- **AND** apply criteria derived from Insurance Law mandatory provisions

### Requirement: Core Mandatory Clause Definition
The system SHALL define core mandatory clauses for each unnamed contract type based on industry standards and governing statutes. Core mandatory clauses are those that are essential for the contract to be legally valid and commercially reasonable.

#### Scenario: Define core mandatory clauses for company_formation
- **WHEN** the company_formation contract type is evaluated
- **THEN** the system SHALL check for the presence of core mandatory clauses including: capital contribution, articles of association, registration obligations, and pre-incorporation liability
- **AND** fail the evaluation if any core mandatory clause is missing

#### Scenario: Define core mandatory clauses for employment
- **WHEN** the employment contract type is evaluated
- **THEN** the system SHALL check for the presence of core mandatory clauses including: work content, labor compensation, working hours, social insurance, and contract termination
- **AND** fail the evaluation if any core mandatory clause is missing

### Requirement: Industry Standard Reference Update Process
The system SHALL provide a controlled process for updating industry standard references, including expert review, testing, and approval. Updates SHALL NOT be applied immediately but SHALL go through a validation process.

#### Scenario: Submit a reference update for review
- **WHEN** a user submits an update to an industry standard reference
- **THEN** the system SHALL mark the update as "pending_review"
- **AND** notify legal experts for review

#### Scenario: Approve a reference update
- **WHEN** legal experts approve an update
- **THEN** the system SHALL mark the update as "approved"
- **AND** schedule the update for deployment in the next release

#### Scenario: Reject a reference update
- **WHEN** legal experts reject an update
- **THEN** the system SHALL mark the update as "rejected"
- **AND** provide feedback on the reasons for rejection

### Requirement: Industry Standard Reference Versioning
The system SHALL maintain version history for all industry standard references, allowing users to track changes over time and rollback to previous versions if needed.

#### Scenario: Create a new version of a reference entry
- **WHEN** a reference entry is updated
- **THEN** the system SHALL create a new version with a unique version number
- **AND** preserve the previous version for historical reference

#### Scenario: Rollback to a previous version
- **WHEN** a user requests to rollback to a previous version
- **THEN** the system SHALL restore the previous version
- **AND** mark the current version as "deprecated"

#### Scenario: Query version history
- **WHEN** a user queries the version history of a reference entry
- **THEN** the system SHALL return all versions with their creation dates, approval status, and change summaries
- **AND** allow comparison between versions
