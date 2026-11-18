## ADDED Requirements

### Requirement: Contract Type Classification System
The system SHALL classify all contract types into two categories: named contracts (民法典典型合同) and unnamed contracts (无名合同). Named contracts are those explicitly defined in the Civil Code (民法典) with specific mandatory clauses. Unnamed contracts are those not explicitly defined in the Civil Code but commonly used in practice.

#### Scenario: Classify a named contract
- **WHEN** a contract type is identified as one of the 19 Civil Code named contracts (sale, lease, loan, guarantee, etc.)
- **THEN** the system SHALL classify it as "named_contract"
- **AND** apply the named contract evaluation framework with strict mandatory clause requirements

#### Scenario: Classify an unnamed contract
- **WHEN** a contract type is not in the 19 Civil Code named contracts
- **THEN** the system SHALL classify it as "unnamed_contract"
- **AND** apply the unnamed contract evaluation framework with industry standard references

#### Scenario: Classification is immutable
- **WHEN** a contract type has been classified
- **THEN** the classification SHALL NOT change unless the contract type definition changes
- **AND** the classification SHALL be stored in the contract type metadata

### Requirement: Named Contract Evaluation Framework
The system SHALL apply a strict evaluation framework for named contracts based on Civil Code mandatory clauses. Each named contract SHALL have type-specific criteria derived from its corresponding Civil Code chapter (e.g., sale contract from Chapter 9, lease contract from Chapter 14).

#### Scenario: Evaluate a named contract with all mandatory clauses
- **WHEN** a named contract contains all mandatory clauses required by its Civil Code chapter
- **THEN** the system SHALL pass the clause_completeness criterion
- **AND** apply type-specific criteria for that contract type

#### Scenario: Evaluate a named contract with missing mandatory clauses
- **WHEN** a named contract is missing one or more mandatory clauses
- **THEN** the system SHALL fail the clause_completeness criterion
- **AND** provide specific feedback on which mandatory clauses are missing

### Requirement: Unnamed Contract Evaluation Framework
The system SHALL apply a flexible evaluation framework for unnamed contracts based on industry standards and commercial reasonableness. Each unnamed contract SHALL have type-specific criteria derived from its governing statutes beyond the Civil Code (e.g., company formation from Company Law, employment from Labor Contract Law).

#### Scenario: Evaluate an unnamed contract with industry standard compliance
- **WHEN** an unnamed contract complies with the applicable industry standards
- **THEN** the system SHALL pass the clause_completeness criterion
- **AND** apply type-specific criteria based on governing statutes

#### Scenario: Evaluate an unnamed contract with commercial reasonableness
- **WHEN** an unnamed contract meets commercial reasonableness standards
- **THEN** the system SHALL pass the commercial_reasonableness criterion
- **AND** provide feedback on areas for improvement

### Requirement: Classification Metadata Storage
The system SHALL store contract type classification metadata in the database, including the classification category (named_contract/unnamed_contract), governing statutes, and industry standard references.

#### Scenario: Store classification metadata for a new contract type
- **WHEN** a new contract type is added to the system
- **THEN** the system SHALL store its classification metadata
- **AND** link it to the appropriate evaluation framework

#### Scenario: Retrieve classification metadata
- **WHEN** a user queries the classification of a contract type
- **THEN** the system SHALL return the classification category, governing statutes, and industry standard references
- **AND** provide links to the applicable evaluation criteria
