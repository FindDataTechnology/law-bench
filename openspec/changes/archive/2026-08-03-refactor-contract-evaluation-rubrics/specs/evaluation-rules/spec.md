## MODIFIED Requirements

### Requirement: Layered Judgment Mechanism for Common Criteria
The system SHALL replace binary judgment (PASS/FAIL) with layered judgment (PASS/HALF_PASS/FAIL) for common criteria. Layered judgment allows the system to distinguish between "fully compliant", "partially compliant", and "non-compliant" states.

#### Scenario: Apply layered judgment to governing_law_present
- **WHEN** evaluating the governing_law_present criterion
- **THEN** the system SHALL apply layered judgment:
  - PASS if a dedicated "Applicable Law" clause explicitly states the governing jurisdiction
  - HALF_PASS if legal references appear in "Recitals" or "Dispute Resolution" sections
  - FAIL if no legal references are present anywhere in the contract
- **AND** record the judgment level in the evaluation results

#### Scenario: Apply layered judgment to legal_citation_accuracy
- **WHEN** evaluating the legal_citation_accuracy criterion
- **THEN** the system SHALL apply layered judgment:
  - PASS if law names and article numbers are accurate and current
  - HALF_PASS if law names are accurate but article numbers are missing or imprecise
  - FAIL if law names are fabricated or repealed
- **AND** provide specific feedback on citation accuracy

#### Scenario: Apply layered judgment to legal_basis_citation
- **WHEN** evaluating the legal_basis_citation criterion
- **THEN** the system SHALL apply layered judgment:
  - PASS if core laws and judicial interpretations are cited with exact document numbers (e.g., 法释〔2020〕17 号)
  - HALF_PASS if core laws are cited with general references (e.g., "Civil Code + relevant judicial interpretations")
  - FAIL if core laws are not cited or cited laws are repealed
- **AND** accept generalized citations as partial compliance

### Requirement: Differentiated Criteria by Contract Classification
The system SHALL apply different evaluation criteria based on contract type classification (named_contract vs unnamed_contract). Named contracts SHALL be evaluated against Civil Code mandatory clauses, while unnamed contracts SHALL be evaluated against industry standards and governing statutes.

#### Scenario: Evaluate a named contract with Civil Code criteria
- **WHEN** evaluating a named contract (e.g., sale, lease, loan)
- **THEN** the system SHALL apply Civil Code-based criteria specific to that contract type
- **AND** check for mandatory clauses defined in the corresponding Civil Code chapter

#### Scenario: Evaluate an unnamed contract with industry standard criteria
- **WHEN** evaluating an unnamed contract (e.g., company_formation, employment, insurance)
- **THEN** the system SHALL apply industry standard criteria based on governing statutes
- **AND** check for core mandatory clauses defined in the industry standard reference table

### Requirement: Flexible Governing Law Citation
The system SHALL accept flexible governing law citations, including references in "Recitals", "Dispute Resolution", or other sections, not just dedicated "Applicable Law" clauses.

#### Scenario: Accept governing law citation in Recitals
- **WHEN** a contract references applicable law in the "Recitals" section
- **THEN** the system SHALL recognize this as a valid governing law citation
- **AND** apply HALF_PASS judgment to the governing_law_present criterion

#### Scenario: Accept governing law citation in Dispute Resolution
- **WHEN** a contract references applicable law in the "Dispute Resolution" section
- **THEN** the system SHALL recognize this as a valid governing law citation
- **AND** apply HALF_PASS judgment to the governing_law_present criterion

#### Scenario: Require dedicated clause for full compliance
- **WHEN** a contract has a dedicated "Applicable Law" clause
- **THEN** the system SHALL apply PASS judgment to the governing_law_present criterion
- **AND** recognize this as the preferred format

### Requirement: Simplified Legal Citation Requirements
The system SHALL simplify legal citation requirements, accepting generalized citations (e.g., "Civil Code + relevant judicial interpretations") as partial compliance, while still requiring exact document numbers for full compliance.

#### Scenario: Accept generalized legal citation
- **WHEN** a contract cites "Civil Code + relevant judicial interpretations" without exact document numbers
- **THEN** the system SHALL apply HALF_PASS judgment to the legal_basis_citation criterion
- **AND** provide feedback suggesting the addition of exact document numbers

#### Scenario: Require exact document numbers for full compliance
- **WHEN** a contract cites laws with exact document numbers (e.g., 法释〔2020〕17 号)
- **THEN** the system SHALL apply PASS judgment to the legal_basis_citation criterion
- **AND** recognize this as the preferred format

#### Scenario: Reject fabricated or repealed laws
- **WHEN** a contract cites fabricated or repealed laws
- **THEN** the system SHALL apply FAIL judgment to the legal_citation_accuracy criterion
- **AND** provide specific feedback on which citations are invalid

### Requirement: Evaluation Criteria Versioning
The system SHALL support multiple versions of evaluation criteria (v1, v2, v3), allowing gradual migration and backward compatibility. New criteria versions SHALL be created through a controlled process with expert review and testing.

#### Scenario: Create a new criteria version
- **WHEN** evaluation criteria are updated
- **THEN** the system SHALL create a new version (e.g., v3) with the updated criteria
- **AND** preserve previous versions (v1, v2) for backward compatibility

#### Scenario: Migrate to a new criteria version
- **WHEN** a new criteria version is approved
- **THEN** the system SHALL allow gradual migration from the old version to the new version
- **AND** support running both versions in parallel during the migration period

#### Scenario: Rollback to a previous criteria version
- **WHEN** issues are discovered with a new criteria version
- **THEN** the system SHALL allow rollback to a previous version
- **AND** preserve all evaluation results from the new version for analysis

## ADDED Requirements

### Requirement: Evaluation Criteria Testing Framework
The system SHALL provide a testing framework for validating new evaluation criteria versions before deployment. The framework SHALL support A/B testing, regression testing, and performance benchmarking.

#### Scenario: Run A/B test on new criteria
- **WHEN** a new criteria version is created
- **THEN** the system SHALL run A/B tests comparing the new version against the old version
- **AND** measure pass rates, false positives, and false negatives

#### Scenario: Run regression test on existing contracts
- **WHEN** a new criteria version is created
- **THEN** the system SHALL run regression tests on a set of existing contracts
- **AND** verify that the new criteria do not introduce unexpected failures

#### Scenario: Benchmark evaluation performance
- **WHEN** a new criteria version is created
- **THEN** the system SHALL benchmark the evaluation performance (time, cost, accuracy)
- **AND** compare against the old version

### Requirement: Evaluation Criteria Feedback Loop
The system SHALL provide a feedback loop for continuously improving evaluation criteria based on test results, user feedback, and legal expert review.

#### Scenario: Collect feedback from test results
- **WHEN** evaluation criteria are tested
- **THEN** the system SHALL collect feedback on false positives, false negatives, and edge cases
- **AND** use the feedback to improve the criteria

#### Scenario: Collect feedback from users
- **WHEN** users provide feedback on evaluation results
- **THEN** the system SHALL record the feedback
- **AND** use it to improve the criteria in the next version

#### Scenario: Incorporate legal expert review
- **WHEN** legal experts review evaluation criteria
- **THEN** the system SHALL incorporate their feedback
- **AND** update the criteria accordingly
