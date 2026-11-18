## Context

The `add-clause-knowledge-base` change (complete, unarchived) created a `clauses` table and a read-only `/clauses` browse + assembly capability:

- **Table** `clauses(id, contract_type, category[base|tagged|custom], section, body, slot_instructions jsonb, law_refs jsonb, province, level, source_path, source_doc_title, body_hash, created_at, updated_at)` with a partial unique index on `(source_path, section, body_hash)`.
- **Store** (`src/clauses/store.py`): `upsert_clause`/`upsert_clauses` (idempotent on the unique index), `delete_clauses(source_path)`, `list_clauses(type, category, province)`, `get_custom_clause(id)`, `count_clauses`, `counts_by_type`, `list_extracted_source_paths`. Category semantics are enforced in `_row` (custom→null source_path; base→national+null province; tagged→local).
- **Extraction** (`src/clauses/extract.py`): `_law_refs_from_body` (derives `《...》` provisions + category) and `_normalize_slot_instructions` (ensures instructions cover body `{{slots}}`) are pure helpers ripe for reuse.
- **Run extraction** (`src/clauses/cli.py`): per document it `delete_clauses(source_path)` then `upsert_clauses(record["clauses"])` - so re-extraction today **wipes** any hand edit to an extracted clause.
- **Web** (`src/web/routes/clauses.py`): `GET /clauses`, `POST /clauses/extract`, `GET /clauses/{type}`, `GET /clauses/{type}/generate` - all read/generate, no mutation.

Constraint: HTML forms only do GET/POST (no PUT/DELETE), so mutations are POST endpoints. The `_ADDITIVE_COLUMNS` pattern in `src/eval/store.py` is the established way to add columns idempotently. `psycopg.types.json.Jsonb` adapts jsonb.

## Goals / Non-Goals

**Goals:**
- Create custom clauses (category=custom) from a form, with `slot_instructions` and `law_refs` auto-derived from the body.
- Edit any clause (body, section, category, province) - including LLM-extracted base/tagged clauses - re-deriving `body_hash`, `slot_instructions`, and `law_refs` from the edited body.
- Delete a clause by id.
- Browse by legal domain (contract type) + category + province + free-text search across bodies.
- Preserve dashboard-created/edited clauses across corpus re-extraction (a `manual` flag).

**Non-Goals:**
- Clause versioning/history, audit log, or undo.
- Bulk import/export (CSV/JSON).
- Role-based access control / auth.
- Re-extracting a single source document from the UI (the CLI remains the extraction entry point).
- Editing the nested `slot_instructions` as a free-form JSON editor (slot names come from `{{slots}}` in the body; labels/descriptions are refined inline or auto-stubbed).

## Decisions

### D1: A `manual` flag preserves dashboard clauses across re-extraction
**Choice**: Add `manual BOOLEAN NOT NULL DEFAULT false` (additive `ALTER` in `ensure_schema`). Dashboard `create_clause`/`update_clause` set `manual=true`. `run_extraction`'s per-document delete becomes `DELETE FROM clauses WHERE source_path=%s AND (manual IS NOT TRUE)` - so re-extracting a document refreshes its auto-extracted clauses but leaves curated ones intact.
**Rationale**: Without this, re-running extraction would wipe every correction an operator made to an extracted clause - making the dashboard's edit feature self-defeating. The flag is the minimal, safe preservation mechanism.
**Alternatives**: A separate `clauses_manual` table - rejected (duplicates the schema and forces a UNION on every read). Skip the whole `source_path` on re-extract if it has manual clauses - rejected (blocks refreshing auto clauses for that document).

### D2: On edit, auto-derive `body_hash`, `slot_instructions`, and `law_refs` from the body
**Choice**: `update_clause(id, {body, section, category, province})` recomputes `body_hash=md5(body)`, re-derives `law_refs` via `extract._law_refs_from_body(body)`, and re-normalizes `slot_instructions` via `extract._normalize_slot_instructions(body, existing_instructions)` - preserving existing labels/descriptions for slots that remain and stubbing any new `{{slot}}`. The operator edits prose + metadata, never raw JSONB.
**Rationale**: The body is the source of truth for slots and cited laws; deriving them keeps the three (body, slots, law_refs) consistent without a nested-form UX. Reusing the existing pure helpers avoids divergence.
**Alternatives**: Let the operator hand-edit `slot_instructions`/`law_refs` JSON - rejected (error-prone, breaks the slot-coverage invariant). Skip re-derivation on edit - rejected (stale slots/law_refs after a body edit).

### D3: Mutations are POST endpoints (HTML forms), under `/clauses`
**Choice**: `POST /clauses/{type}/clauses/{id}` (update), `POST /clauses/{type}/clauses/{id}/delete` (delete), `GET/POST /clauses/{type}/new` (create). `GET /clauses/{type}/clauses/{id}` renders the edit form. All redirect back to the detail/browse page on success.
**Rationale**: HTML forms can't PUT/DELETE; distinct POST endpoints are the established pattern. Keeping everything under `/clauses` co-locates management with the existing browse/generate routes.
**Alternatives**: A JSON REST API (`PUT/DELETE /clauses/{id}`) consumed by a JS SPA - rejected (heavier; the rest of the app is server-rendered Jinja).

### D4: Editing extracted (base/tagged) clauses is allowed and flips `manual=true`
**Choice**: Any clause - base, tagged, or custom - can be edited via the dashboard; the first dashboard edit of an extracted clause sets `manual=true` (so D1 preserves it). Reclassifying category/province is part of the edit form (e.g. demote a tagged clause to base, or assign a province).
**Rationale**: Operators must be able to fix extraction mistakes (wrong section, wrong province, off prose) and reorganize - that is the point of a management dashboard. Flipping `manual` on edit is the natural preservation trigger.
**Alternatives**: Read-only extracted clauses + editable custom only - rejected (can't correct extraction). A separate "override" record per edited clause - rejected (complex; the flag is enough for v1).

### D5: Free-text search across clause bodies, scoped by domain/category/province
**Choice**: `search_clauses(query, *, contract_type, category, province)` -> `body ILIKE '%query%'` (and `source_doc_title`), composed with the existing filters. Wired into `GET /clauses` and `GET /clauses/{type}` as a `q` query param.
**Rationale**: With hundreds of clauses per type, a body search is necessary to find the clause to edit. `ILIKE` is adequate at this scale; no full-text index needed for v1.
**Alternatives**: Postgres `tsvector` full-text search - rejected (premature; ILIKE on ~thousands of rows is fine). Elasticsearch - rejected (out of scope; the clause DB is relational).

## Risks / Trade-offs

- **[Re-extraction duplicates edited clauses]** After editing an extracted clause (`manual=true`) and re-extracting its source, the new auto-extracted version is inserted alongside the manual one (different `body_hash`) - a near-duplicate. Mitigation: the dashboard surfaces `manual` + `source_path` so the operator can delete the stale auto copy. Acceptable for v1.
- **[ILIKE scan cost]** `ILIKE '%q%'` is a sequential scan. Fine for thousands of rows; revisit with a GIN tsvector if the corpus grows past ~50k clauses.
- **[No auth]** Anyone reaching the web app can mutate clauses. Acceptable in the current trusted/k3s deployment; auth is a separate concern.
- **[Manual flag default false]** Existing extracted rows get `manual=false` automatically (additive column); re-extraction can still refresh them - the intended behavior.
