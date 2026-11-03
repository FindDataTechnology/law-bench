# targeted-self-iteration Specification

## Purpose

Introduce a coverage analysis step after evaluation that maps failing criteria to missing legal_topics, generate targeted custom clauses for identified gaps, and differentiate pipeline behavior between named and unnamed contracts.

## Requirements

### Requirement: Coverage analysis node in pipeline

The system MUST introduce a new coverage analysis step after evaluation that maps failing criteria to missing legal_topics.

#### Scenario: Parse failing criteria
- **WHEN** self-heal pipeline evaluates a contract and receives failing criteria
- **THEN** each failure includes `{criterion_id, verdict="fail", reasoning}` which is passed to coverage analysis

#### Scenario: Map criterion to legal_topic
- **WHEN** coverage analysis receives `criterion_id="ownership_transfer"`
- **THEN** it looks up the rubric and confirms this equals legal_topic "ownership_transfer" (1-to-1 mapping)

#### Scenario: Check topic clause availability
- **WHEN** coverage analysis queries for existing assembly-ready clauses with `legal_topic="ownership_transfer"` AND `stance="balanced"`
- **THEN** response shows count of available clauses OR reports gap if count=0

#### Scenario: Report coverage gaps
- **WHEN** a legal_topic has zero assembly-ready clauses for a given stance/scenario
- **THEN** coverage gaps are recorded as: `[{legal_topic: "...", stance: "...", scenario: "..."}]`

### Requirement: Targeted clause generation on failures

The system MUST generate new custom clauses targeting specific missing legal_topics rather than blind exclusion.

#### Scenario: Generate clause for ownership_transfer gap
- **WHEN** coverage analysis reports gap on legal_topic="ownership_transfer"
- **THEN** improve node prompts LLM: "Generate a balanced-stance sale clause about ownership transfer citing Civil Code article 224"

#### Scenario: Generate clause on inspection_period gap
- **WHEN** coverage analysis reports gap on legal_topic="inspection_period"
- **THEN** improve node prompts LLM with criterion guidance: "Write a clause stating 'buyer shall inspect within X days' matching rubric guidance for inspection_period"

#### Scenario: New clause gets tagged with legal_topic
- **WHEN** LLM generates a new clause body
- **THEN** the improve node tags it with `tags.legal_topic=<matching_criterion_name>` before adding to custom_clause_ids

#### Scenario: Add generated clause to next iteration
- **WHEN** improved state includes new clause IDs
- **THEN** next `generate` call uses `custom_clause_ids` including the newly generated clauses

### Requirement: Self-heal improve node behavior

The improve node MUST diagnose failures by mapping failing criteria to `legal_topic` coverage and generating targeted clauses for gaps, replacing the old "exclude thin overrides" logic with "identify missing topics + generate targeted clauses".

#### Scenario: Diagnose failure by legal_topic (NEW)
- **WHEN** improve node receives failing criteria
- **THEN** it performs: `(1) map criterion->topic (2) check topic coverage (3) if gap->generate targeted clause`

#### Scenario: No longer blindly excludes all thin clauses
- **WHEN** a custom clause is marked thin (few slots) BUT covers a critical topic (conf=1.0 fail)
- **THEN** improve node does NOT exclude it; instead it flags the topic gap for targeted generation

#### Scenario: Recommendations now include topic-based actions
- **WHEN** improve node creates recommendations
- **THEN** recommendation objects include `"action_type": "generate_topic_clause"` or `"action_type": "reject_topic_clause"` with rationale

#### Scenario: Previous exclusion logic retained for debug
- **WHEN** old-style exclusion decisions were logged
- **THEN** they remain as deprecated paths but are not executed by default (for audit trail only)

### Requirement: Named vs unnamed contract differentiation

The pipeline MUST set `max_iterations` and auto-reject thresholds based on contract classification: aggressive defaults for named contracts (deterministic structure from Civil Code articles) and conservative defaults for unnamed contracts.

#### Scenario: Classify named contract
- **WHEN** system processes `contract_type="sale"`
- **THEN** `is_named_contract()` returns true AND pipeline sets `max_iterations=3`, `auto_reject_threshold=3`

#### Scenario: Classify unnamed contract
- **WHEN** system processes `contract_type="employment"`
- **THEN** `is_unnamed_contract()` returns true AND pipeline sets `max_iterations=5`, `auto_reject_threshold=5`

#### Scenario: Named contract aggressive auto-generation
- **WHEN** named contract fails coverage on a topic
- **THEN** improve node generates clause citing specific Civil Code article (e.g., "《民法典》第 224 条")

#### Scenario: Unnamed contract conservative auto-generation
- **WHEN** unnamed contract fails coverage on a topic
- **THEN** improve node generates clause citing applicable statute generically (e.g., "劳动合同法相关规定") without specific article numbers
