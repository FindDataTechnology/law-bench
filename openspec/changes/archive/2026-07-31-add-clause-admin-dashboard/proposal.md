## Why

The clause knowledge base (`add-clause-knowledge-base`, just built) is **read-only**: `/clauses` browses extracted clauses and assembles contracts, but there is no way to correct a mis-extracted clause, add a custom clause by hand, reclassify one across the 原始(base)/标签(tagged)/自定义(custom) categories, or delete a bad one. The LLM extraction is good but not perfect, and the three categories are meant to be curated. This change adds a **management dashboard** (CRUD) over the `clauses` table - organized by legal domain (contract type) and category - so an operator can tune, create, and organize clauses across the three categories, with manual edits preserved across re-extraction.

## What Changes

- **Clause CRUD store layer** (`src/clauses/store.py`): `update_clause(id, fields)` (UPDATE by id - re-derives `body_hash` from the new body), `delete_clause(id)` (DELETE by id), and `create_clause(clause)` for dashboard-created custom clauses. All dashboard writes set `manual=true`.
- **`manual` column** (additive `ALTER` in `src/eval/store.py` `ensure_schema`): marks clauses created or edited via the dashboard so they survive re-extraction.
- **Re-extraction preserves manual edits**: `run_extraction`'s per-document delete drops only `manual IS NOT TRUE` clauses for the source, so re-running extraction refreshes auto-extracted clauses without wiping curated ones.
- **Auto-derive on edit**: when a clause body is edited, `slot_instructions` is re-normalized to cover the body's `{{slots}}` (preserving existing labels/descriptions, stubbing new ones) and `law_refs` is re-derived from the body's `《...》` provisions - so the operator edits prose, not JSON.
- **Management routes + templates** (`src/web/routes/clauses.py` + new templates):
  - `GET /clauses/{type}` (enhanced): per-clause edit/delete links + a "new custom clause" action.
  - `GET /clauses/{type}/clauses/{id}` - clause detail + edit form (body, section, category, province, slots preview).
  - `POST /clauses/{type}/clauses/{id}` - update; `POST .../{id}/delete` - delete.
  - `GET /clauses/{type}/new` + `POST /clauses/{type}/new` - create a custom clause.
  - Browse filters (category, province) + a text search across clause bodies.
- **No changes** to the extraction pipeline, assembly generator, `document-generation`, or `contract-templates`.

## Capabilities

### New Capabilities
- `clause-admin`: a CRUD management dashboard over the `clauses` table - create custom clauses, edit any clause (including reclassifying across base/tagged/custom and tuning LLM-extracted bodies), delete clauses, and browse by legal domain/category/province with text search - with manual edits preserved across corpus re-extraction.

### Modified Capabilities
<!-- None. clause-knowledge-base (table + store + extraction + assembly) is consumed unchanged; this change adds the management layer on top. -->

## Impact

- **New code**: `src/web/routes/clauses.py` (extended with CRUD routes) + new templates `clause_edit.html`, `clause_new.html`; `src/clauses/store.py` (`update_clause`, `delete_clause`, `create_clause`, `search_clauses`).
- **New tests**: `tests/test_clauses_admin_store.py` (update/delete/create + manual flag + search), `tests/test_clauses_admin_web.py` (create/edit/delete routes + preservation).
- **Modified code**: `src/eval/store.py` (additive `manual` column + `_ADDITIVE_COLUMNS`); `src/clauses/cli.py` `run_extraction` (per-doc delete skips `manual IS NOT TRUE`); `src/web/templates/clauses_detail.html` (edit/delete/new links); `src/web/templates/clauses_list.html` (search box).
- **Dependencies**: none new.
- **Data**: additive `manual` column on `clauses` (default false); existing rows unaffected.
- **Operations**: dashboard at `/clauses` whenever the web app runs; mutations are synchronous (low volume).
- **Out of scope**: bulk import/export, clause versioning/history, role-based access control, re-extraction of a single source from the UI.
