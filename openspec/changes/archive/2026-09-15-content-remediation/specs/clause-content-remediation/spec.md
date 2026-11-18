## Purpose

Deterministic, reversible remediation of clause-library content defects on the production clauses store: detect (region leakage, extraction artifacts, duplicates, corrupted review metadata, hardcoded commercial values), repair with per-clause before-snapshots, and roll back without destructive operations.

## ADDED Requirements

### Requirement: Deterministic Defect Detection over the Clause Library
The remediation tooling SHALL run zero-LLM, rule-based checks over an offline dump of the clauses store and produce a machine-readable report enumerating, per defect class, the affected clause ids. Defect classes SHALL include region leakage (place name + local regulation citation), signature-shell residue (签订地点/签订日期/盖章 signature blocks inside clause bodies), underscore fill-in blanks, table fragments, exact-body duplicates, hardcoded commercial values (money amounts / dates / company names outside statutory defaults), and non-review metadata keys inside review states.

#### Scenario: Full-library scan produces an id-level report
- **WHEN** the detector runs over a dump of all clauses in the store
- **THEN** it emits a report file containing, for each defect class, the count and the clause ids affected, with zero unparseable rows tolerated silently (parse errors are counted and reported)

#### Scenario: Statutory values are not flagged
- **WHEN** a clause body contains a statutory time limit or statutory ratio (e.g. "15日内", "不超过20%")
- **THEN** the detector does not flag it as a hardcoded commercial value

### Requirement: Reversible Mutations with Before-Snapshots
The remediation driver SHALL, before writing any clause body or review state, persist a before-snapshot of the affected clauses to disk (full pre-mutation row content), and SHALL write a per-clause result file recording the change applied. All duplicate handling SHALL use review-state rejection (recoverable by re-approval), never deletion. A rollback path SHALL exist that restores clause bodies from the before-snapshots and re-approves rejected duplicates.

#### Scenario: Every applied rewrite has a restore source
- **WHEN** a clause body is rewritten by the remediation driver
- **THEN** a before-snapshot containing the prior body exists on disk and a result file records the clause id, defect class, and new body

#### Scenario: Duplicate rejection is recoverable
- **WHEN** a duplicate clause is rejected by the dedupe pass
- **THEN** the clause row still exists with its body intact and can be restored to assembly by re-approving its review state

#### Scenario: Rollback restores prior content
- **WHEN** the operator restores from the before-snapshots taken before a remediation batch
- **THEN** the affected clause bodies equal their pre-batch content

### Requirement: Region-Leak Generalization for Scenario-Bearing Clauses
For clauses that enter assembly via a scenario tag and whose bodies hardcode a specific province/city regulation or a specific local arbitration body, the remediation SHALL replace the local binding with a national-law formulation and SHALL express the dispute-resolution venue as a fill-in placeholder. The rewritten clause SHALL preserve the original legal obligations and SHALL produce zero residual region-lint matches. Deliberately scenario-intrinsic region mentions (e.g. 赴台游 scenario's 台湾地区 references) SHALL be exempted.

#### Scenario: Local regulation citation is generalized
- **WHEN** a scenario-bearing clause cites 《深圳市保障性住房条例》 in its preamble
- **THEN** the rewritten body cites national-level law or a region-neutral formulation ("按照国家及当地有关规定执行") instead

#### Scenario: Hardcoded arbitration venue becomes a placeholder
- **WHEN** a scenario-bearing dispute-resolution clause names a specific city arbitration commission
- **THEN** the rewritten body uses a jurisdiction/arbitration placeholder instead of the city name

#### Scenario: Scenario-intrinsic region mentions are kept
- **WHEN** a clause belongs to the 大陆居民赴台湾地区旅游 scenario and references 台湾地区 as part of the trip subject
- **THEN** the clause is not rewritten for region leakage

### Requirement: Extraction-Artifact Stripping
The remediation SHALL strip signature-shell lines (signature/seal/date/place fields), convert underscore fill-in blanks into slot placeholders where they represent commercial blanks, and remove table fragments from clause bodies, while preserving the clause's substantive legal content. A remediated body SHALL NOT begin with a section heading (section headings are added at assembly time).

#### Scenario: Signature shell is removed from a clause body
- **WHEN** a clause body contains 甲方（盖章）：__________ signature lines
- **THEN** the remediated body no longer contains them and retains the surrounding operative text

#### Scenario: Underscore commercial blank becomes a slot
- **WHEN** a clause body contains 本合同一式___份
- **THEN** the remediated body expresses the count as a slot placeholder

#### Scenario: Legitimate closing clauses survive
- **WHEN** a clause is an 附则/生效 clause whose signature-adjacent text carries operative meaning (e.g. specifying copy counts or effectiveness)
- **THEN** stripping removes only the signature-shell residue, not the operative sentence

### Requirement: Review-State Metadata Cleanup
The remediation SHALL remove metadata keys (keys prefixed with `_`, e.g. import timestamps, source hashes, notes) from clause review states, leaving only genuine review dimensions with pending/approved/rejected values. The cleanup SHALL be idempotent.

#### Scenario: Importer metadata is stripped
- **WHEN** a clause's review state contains `_imported_at` and `_source_hash` alongside genuine dimensions
- **THEN** after cleanup the review state contains only the genuine dimensions with unchanged values

#### Scenario: Re-running cleanup is a no-op
- **WHEN** the cleanup runs on a clause whose review state has no `_`-prefixed keys
- **THEN** the review state is unchanged
