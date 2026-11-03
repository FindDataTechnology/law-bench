# type-validation-constraints Specification

## Purpose
TBD - created by archiving change generator-rules-integration. Update Purpose after archive.

## Requirements

### Requirement: Standalone type_validations table

The system MUST store legal hard constraints in a `type_validations` table, loaded from the generator's `validation/*.yaml` (inherited chain merged via the loader's `validations_for(type)`), with columns: `contract_type`, `constraint_id`, `kind` (required|max|min|max_duration|max_deposit_months|regex|oneof|always), `field`, `params` (jsonb), `severity` (error|warning), `law_ref`, `inherited_from`. The table is keyed uniquely on `(contract_type, constraint_id)`.

#### Scenario: Constraint loaded from generator YAML
- **WHEN** the importer runs for `lease`
- **THEN** rows are inserted for `lease_term_max` (kind=max_duration, params={max:20,unit:years}, severity=error, law_ref=民法典§705), `deposit_max_3m` (max_deposit_months, {max:3}, error), and `safety_termination` (always, §731)
- **AND** constraints inherited from the parent `lease` level are merged with leaf-level `lease.immovable.house` constraints

### Requirement: Draft compliance check is explicit, never automatic

The system MUST expose a `validate_draft(contract_type, draft|slots)` function that runs all `type_validations` for the type's inheritance chain against a finished draft and returns `{errors, warnings, passed}`. This function MUST NOT be called by `contract_generate`, the fill step, `self_heal_pipeline_run`, or `auto_reject_pipeline_run`. Generation is unchanged.

#### Scenario: Validation runs only when explicitly invoked
- **WHEN** a draft is assembled via `contract_generate` and `self_heal_pipeline_run`
- **THEN** `type_validations` is not consulted during assembly or self-heal
- **AND** a caller must explicitly invoke `validate_draft` (or the `validation_check` MCP tool) to obtain compliance results

#### Scenario: Over-limit term flagged
- **WHEN** `validate_draft("lease", {租金金额:"3000", 起租日期:"2026-01-01", 止租日期:"2050-01-01"})` is called
- **THEN** the result includes an error: constraint `lease_term_max`, message naming the 20-year cap, law_ref 民法典§705, severity error
- **AND** `passed` is false

#### Scenario: Missing always-clause flagged
- **WHEN** a lease draft omits the 安全健康解约权 clause (kind=always, §731)
- **THEN** the result includes an error for `safety_termination`
- **AND** `passed` is false

#### Scenario: Clean draft passes
- **WHEN** a draft satisfies all constraints
- **THEN** `passed` is true and `errors` is empty (warnings may still be present)

### Requirement: MCP tools for validation

The system MUST expose two MCP tools: `validation_list(contract_type)` returning the constraints for a type's inheritance chain, and `validation_check(contract_type, draft|slots)` returning the compliance result. These are the only way the validation layer is surfaced; no generation tool gains a validation parameter.

#### Scenario: List constraints
- **WHEN** `validation_list("lease")` is called
- **THEN** it returns all `type_validations` rows for `lease` and its inherited levels, each with kind/params/severity/law_ref

#### Scenario: Check a draft
- **WHEN** `validation_check("lease", draft_markdown)` is called
- **THEN** it parses the draft's slots and returns `{errors, warnings, passed}`
