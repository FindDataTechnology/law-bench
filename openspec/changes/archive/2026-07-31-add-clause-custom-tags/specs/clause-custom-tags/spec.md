## ADDED Requirements

### Requirement: Clause Tag Storage
The system SHALL store a controlled-vocabulary tag object on every clause in a `tags JSONB` column (default `'{}'`), added idempotently via `ALTER TABLE IF EXISTS ... ADD COLUMN IF NOT EXISTS`. The column SHALL hold any subset of the currently-registered tag dimensions. `validate_tags(tags)` SHALL drop unknown keys and SHALL raise `ValueError` for a registered key with a value outside its vocabulary. Existing rows SHALL default to `'{}'` (untagged) and be unaffected.

#### Scenario: Additive column defaults to untagged
- **WHEN** the `tags` column is added to a `clauses` table with existing rows
- **THEN** every pre-existing clause has `tags = {}` and is returned unchanged by `list_clauses`

#### Scenario: Unknown tag value is rejected
- **WHEN** `validate_tags({"stance": "pro_A"})` is called (typo)
- **THEN** a `ValueError` is raised

#### Scenario: Unknown tag key is dropped
- **WHEN** `validate_tags({"stance": "pro_a", "mood": "happy"})` is called
- **THEN** the returned dict contains `stance: "pro_a"` and omits `mood`

### Requirement: Growable Tag Vocabulary
The system SHALL maintain a controlled vocabulary that starts with the universal starter set `stance ∈ {pro_a, pro_b, balanced}`, `strength ∈ {strong, standard, mild}`, `risk ∈ {high, medium, low}`, `mandatory ∈ {mandatory, default, recommended}`, and SHALL grow via `register_tag_dim(name, values)` as per-type analysis proposes type-specific dimensions. The employment-specific dimensions `special_restriction_period ∈ {probation, service_period, non_compete, declassification, none}` and `working_hours_system ∈ {standard, comprehensive, flexible, part_time}` SHALL be registered (from the employment pilot). A dimension not in the current vocabulary SHALL be rejected by `validate_tags`.

#### Scenario: Vocabularies are registered
- **WHEN** `TAG_VOCAB` is read after startup
- **THEN** it contains `stance`, `strength`, `risk`, `mandatory`, `special_restriction_period`, and `working_hours_system` with their listed value sets

#### Scenario: A type-specific dimension is registered
- **WHEN** `register_tag_dim("vam_mechanism", ["performance", "buyback", "valuation_adjustment"])` is called
- **THEN** a subsequent `validate_tags({"vam_mechanism": "buyback"})` returns `{"vam_mechanism": "buyback"}`

### Requirement: Tags Persist Through Create and Edit
`create_clause(clause)` and `update_clause(id, fields)` SHALL accept and persist a `tags` dict (validated via `validate_tags`). Editing a clause's `body` SHALL NOT alter its `tags` (tags are curatorial, not body-derived - unlike `slot_instructions` and `law_refs`, which remain re-derived). `update_clause` SHALL preserve existing tags when `tags` is not supplied in `fields`. Dashboard writes SHALL continue to set `manual=true`.

#### Scenario: Create a clause with tags
- **WHEN** a clause is created with `tags={"stance":"pro_a","strength":"strong","risk":"high","mandatory":"default"}`
- **THEN** the stored clause carries exactly those tags and `manual=true`

#### Scenario: Body edit preserves tags
- **GIVEN** a clause with `tags={"stance":"pro_a"}`
- **WHEN** the operator edits only the `body` and saves (no `tags` in the update)
- **THEN** the clause's `body_hash`/`slot_instructions`/`law_refs` are re-derived but `tags` remains `{"stance":"pro_a"}`

#### Scenario: Tags are not body-derived
- **WHEN** a clause body is edited to flip its effective stance
- **THEN** the `stance` tag is unchanged (the operator must re-set it via the form)

### Requirement: Tag Facets on Browse
`list_clauses(...)` and `search_clauses(...)` SHALL accept an optional `tags` filter (a dict of dimension-to-value) and return only clauses whose `tags->>'<dim>' = '<value>'` for each supplied dimension, composed with the existing `contract_type`/`category`/`province`/`q` filters. `GET /clauses` and `GET /clauses/{type}` SHALL accept any registered tag dimension as a query param mapping to this filter.

#### Scenario: Filter by stance
- **WHEN** `GET /clauses/employment?stance=pro_a` is requested
- **THEN** only employment clauses with `tags->>'stance' = 'pro_a'` are listed, in canonical section order

#### Scenario: Facets compose with existing filters
- **WHEN** `list_clauses("employment", category="custom", tags={"special_restriction_period":"non_compete"})` is called
- **THEN** only custom employment clauses tagged `special_restriction_period=non_compete` are returned

### Requirement: Assembly by Stance
`generate_contract_assembled(contract_type, *, province=None, custom_clause_ids=None, stance=None, format="pdf", out_dir=None, db=None)` SHALL, when `stance` is set, restrict the selected custom clauses to those with `tags->>'stance' = stance`. Base and tagged clause selection SHALL be unaffected by `stance`. An unknown `contract_type` SHALL continue to raise `NotFoundError`.

#### Scenario: Assemble a pro-甲方 contract
- **WHEN** `generate_contract_assembled("employment", stance="pro_a")` is called
- **THEN** the assembled body includes the base employment clauses plus only `pro_a` custom clauses, in canonical section order

#### Scenario: Stance does not affect base/tagged
- **WHEN** `generate_contract_assembled("sale", stance="pro_a")` is called
- **THEN** every base sale clause is still included regardless of its (likely untagged) tags

#### Scenario: Unknown type still raises
- **WHEN** `generate_contract_assembled("does_not_exist", stance="pro_a")` is called
- **THEN** `NotFoundError` is raised

### Requirement: Per-Type Seed Manifest
The system SHALL provide a per-contract-type seed manifest at `data/clause_seeds/<contract_type>.yaml`, holding `{tags: [{name, values}], clauses: [{family, section, body, stance?, strength?, slot_instructions?}], skipped: [{item, reason}]}` where `slot_instructions` is `[{name, label, description, example, required}]`. A clause `body` MAY contain `{{slot}}` placeholders; every `{{slot}}` in `body` SHALL have a matching `slot_instructions` entry (by `name`). A clause that cites a statute SHALL cite a real, current one by name and article number; an article number that cannot be verified SHALL be marked `待核` rather than fabricated, and a clause with no direct statute SHALL be marked 合同约定. Each clause `section` SHALL be one of the canonical 10. The `skipped` list SHALL record, for each candidate evaluated and rejected, the item and a one-line reason. `load_manifest(path)` SHALL validate this schema.

#### Scenario: Manifest cites real statutes
- **WHEN** `data/clause_seeds/employment.yaml` is loaded
- **THEN** every clause's `body` cites a real statute (e.g. 《中华人民共和国劳动合同法》第二十二条) and no article number is fabricated

#### Scenario: Skipped items carry a reason
- **WHEN** the employment manifest's `skipped` list is read
- **THEN** it includes 试用期 / 劳动报酬 / 社会保险 / 劳动保护, each with a statutory reason (法定强制 or 必备条款 already in base)

#### Scenario: Bad manifest is rejected
- **WHEN** `load_manifest` is given a manifest whose clause has an unknown `section`, a `stance` value outside the vocabulary, or a `{{slot}}` in `body` with no matching `slot_instructions` entry
- **THEN** validation raises an error naming the offending field

### Requirement: Idempotent Seed Loader
`scripts/seed_stance_clauses.py [--type <contract_type>]` SHALL read the manifest(s), delete existing seed clauses for each type (identified by `source_doc_title = 'seed:<contract_type>'`), then insert the manifest's clauses via `create_clause` with `category=custom, manual=true`, the manifest's `tags`, and the manifest's `slot_instructions` (so `create_clause`'s `_finalize` preserves them via `_normalize_slot_instructions`). Re-running SHALL NOT duplicate clauses. Running without `--type` SHALL load all manifests present.

#### Scenario: Seed load is idempotent
- **WHEN** `seed_stance_clauses.py --type employment` is run twice
- **THEN** the `clauses` table contains one copy of each seeded employment clause, with no duplicates, and each carries `manual=true` and its manifest tags

#### Scenario: Load all manifests
- **WHEN** `seed_stance_clauses.py` is run with no `--type`
- **THEN** every manifest under `data/clause_seeds/` is loaded

### Requirement: Per-Type Coverage Audit
Every one of the 41 contract types SHALL have gone through the analyze -> evaluate -> decide flow, recorded either as a seed manifest with added clauses/tags or as an explicit `skipped`-only manifest (nothing new) with reasons. A coverage index (`data/clause_seeds/INDEX.md`) SHALL list, per type, the counts of added clauses and skipped items, so the honest-skip audit trail is visible.

#### Scenario: Every type is accounted for
- **WHEN** the coverage index is read
- **THEN** each of the 41 contract types appears with an "added N / skipped M" entry (M may be all candidates for a type with nothing new)
