## ADDED Requirements

### Requirement: Create Custom Clause
The system SHALL let an operator create a custom clause via a form. `GET /clauses/{type}/new` SHALL render a create form (section, body, category defaulting to `custom`, province). `POST /clauses/{type}/new` SHALL create the clause with `category=custom`, `source_path=null`, `manual=true`, re-derive `body_hash`/`slot_instructions`/`law_refs` from the body, and redirect to the type's clause list. `create_clause(clause)` SHALL set `manual=true` and `source_path=null` for custom clauses.

#### Scenario: Create a custom clause
- **WHEN** the operator posts a section `附则` and body `本合同一式{{n_copies}}份。` to `/clauses/sale/new`
- **THEN** a clause is created with `category="custom"`, `source_path` null, `manual=true`, a `body_hash`, `slot_instructions` covering `n_copies`, and `law_refs` derived from any `《...》` in the body

#### Scenario: Custom clause has no source path
- **WHEN** a custom clause is created via the dashboard
- **THEN** its `source_path` is null and `manual` is true

### Requirement: Edit Clause
The system SHALL let an operator edit any clause (base, tagged, or custom) by id. `GET /clauses/{type}/clauses/{id}` SHALL render an edit form pre-filled with the clause's `section`, `body`, `category`, and `province`. `POST /clauses/{type}/clauses/{id}` SHALL update `section`, `body`, `category`, `province`; re-derive `body_hash` from the body; re-derive `slot_instructions` (preserving existing labels/descriptions for surviving slots, stubbing new ones); re-derive `law_refs` from the body's `《...》`; set `manual=true`; and redirect to the clause's type list. `update_clause(id, fields)` SHALL raise `NotFoundError` for an unknown id.

#### Scenario: Edit a clause body re-derives slots and law refs
- **WHEN** the operator edits a clause's body to `甲方：{{party_a}}，依据《民法典》。` and saves
- **THEN** the clause's `body_hash` changes, `slot_instructions` covers `party_a`, `law_refs` contains `中华人民共和国民法典`, and `manual` is true

#### Scenario: Edit an extracted clause marks it manual
- **WHEN** the operator edits a `base` clause (originally `manual=false`) and saves
- **THEN** the clause's `manual` becomes true (so re-extraction preserves it)

#### Scenario: Unknown clause id raises
- **WHEN** `update_clause(999999, {...})` is called
- **THEN** `NotFoundError` is raised

### Requirement: Delete Clause
The system SHALL let an operator delete a clause by id. `POST /clauses/{type}/clauses/{id}/delete` SHALL delete the clause and redirect to the type list. `delete_clause(id)` SHALL return the count deleted and raise `NotFoundError` for an unknown id.

#### Scenario: Delete a clause
- **WHEN** the operator posts to `/clauses/sale/clauses/{id}/delete`
- **THEN** the clause is removed and `list_clauses` no longer returns it

#### Scenario: Unknown clause id raises
- **WHEN** `delete_clause(999999)` is called
- **THEN** `NotFoundError` is raised

### Requirement: Manual-Edit Preservation Across Re-extraction
The system SHALL preserve dashboard-created or -edited clauses when the corpus is re-extracted. Re-extraction's per-document delete SHALL remove only clauses with `manual IS NOT TRUE` for that source_path; clauses with `manual=true` SHALL remain. The `manual` column SHALL be added idempotently (`ALTER TABLE IF EXISTS ... ADD COLUMN IF NOT EXISTS`) and default to false.

#### Scenario: Re-extraction preserves manual clauses
- **GIVEN** a source_path has one auto-extracted clause (`manual=false`) and one dashboard-edited clause (`manual=true`)
- **WHEN** that source is re-extracted
- **THEN** the auto-extracted clause is deleted and refreshed, and the manual clause remains unchanged

#### Scenario: Existing rows default to manual=false
- **WHEN** the `manual` column is added
- **THEN** every pre-existing extracted clause has `manual=false` (and can still be refreshed by re-extraction)

### Requirement: Management Dashboard Browse with Search
The system SHALL let an operator browse clauses by legal domain (contract type), category, province, and free-text query. `GET /clauses` and `GET /clauses/{type}` SHALL accept a `q` query param and return clauses whose `body` or `source_doc_title` contains `q` (case-insensitive), composed with the category/province filters. Each clause row SHALL expose edit and delete actions.

#### Scenario: Search clauses by body text
- **WHEN** `GET /clauses/sale?q=违约金` is requested
- **THEN** only sale clauses whose body contains `违约金` are listed, in canonical section order

#### Scenario: Browse shows edit/delete actions
- **WHEN** `GET /clauses/sale` is requested
- **THEN** each clause row links to its edit form and a delete action, plus a "new custom clause" action

### Requirement: Slot and Law-Ref Derivation on Edit
The system SHALL keep `slot_instructions` and `law_refs` consistent with the clause body on every create/update. `slot_instructions` SHALL cover every `{{slot}}` in `body` (reusing `src.clauses.extract._normalize_slot_instructions`); `law_refs` SHALL be the `《...》` provisions in `body` categorized via `src.eval.legal_refs` (reusing `src.clauses.extract._law_refs_from_body`). No clause SHALL have a `{{slot}}` without a matching instruction after a dashboard write.

#### Scenario: Slots cover body after edit
- **WHEN** a clause body with `{{party_a}}` and `{{subject}}` is saved (instructions provided only for `party_a`)
- **THEN** the saved `slot_instructions` includes an entry for both `party_a` and `subject`

#### Scenario: Law refs derived from body
- **WHEN** a clause body citing `《中华人民共和国民法典》` and `《吉林省物业管理条例》` is saved
- **THEN** the saved `law_refs` contains both, each with a `category` and `category_zh`
