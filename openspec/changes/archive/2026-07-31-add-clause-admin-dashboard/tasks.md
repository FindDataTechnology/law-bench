## 1. Schema + store CRUD

- [x] 1.1 Add `manual BOOLEAN NOT NULL DEFAULT false` to `clauses` via `_ADDITIVE_COLUMNS` in `src/eval/store.py` (`ALTER TABLE IF EXISTS clauses ADD COLUMN IF NOT EXISTS manual BOOLEAN NOT NULL DEFAULT false;`); include `manual` in `_row_to_dict`
- [x] 1.2 Implement `src/clauses/store.py` `create_clause(clause, db=None)`: enforce `category=custom` -> `source_path=null` + `manual=true`; re-derive `body_hash`; reuse `_row`; return id
- [x] 1.3 Implement `update_clause(clause_id, fields, db=None)`: UPDATE by id; re-derive `body_hash` from the new body; set `manual=true` and `updated_at`; raise `NotFoundError` if 0 rows
- [x] 1.4 Implement `delete_clause(clause_id, db=None)`: DELETE by id; return count; raise `NotFoundError` if 0 rows
- [x] 1.5 Implement `search_clauses(q, *, contract_type=None, category=None, province=None, db=None)`: `body ILIKE %q% OR source_doc_title ILIKE %q%`, composed with existing filters, ordered by section rank; `q=None/""` -> no body filter (delegate to `list_clauses`)
- [x] 1.6 Have `update_clause` re-derive `slot_instructions` via `extract._normalize_slot_instructions(body, existing)` and `law_refs` via `extract._law_refs_from_body(body)` (see spec: Slot and Law-Ref Derivation on Edit)

## 2. Re-extraction preservation

- [x] 2.1 Change `src/clauses/cli.py` `run_extraction` per-document delete to `DELETE FROM clauses WHERE source_path=%s AND (manual IS NOT TRUE)` (new `delete_auto_clauses(source_path, db)` in `store.py`) so manual clauses survive
- [x] 2.2 Verify a re-extract of an already-extracted source refreshes auto clauses but leaves `manual=true` clauses intact

## 3. Web routes (CRUD)

- [x] 3.1 `GET /clauses/{type}/new` -> render `clause_new.html` form (section, body, category=custom default, province)
- [x] 3.2 `POST /clauses/{type}/new` -> `create_clause`; redirect to `/clauses/{type}`
- [x] 3.3 `GET /clauses/{type}/clauses/{id}` -> render `clause_edit.html` pre-filled (section, body, category, province, derived slots/law_refs preview); 404 if id missing
- [x] 3.4 `POST /clauses/{type}/clauses/{id}` -> `update_clause`; redirect to `/clauses/{type}`
- [x] 3.5 `POST /clauses/{type}/clauses/{id}/delete` -> `delete_clause`; redirect to `/clauses/{type}`
- [x] 3.6 Add `q` query param to `GET /clauses` and `GET /clauses/{type}` calling `search_clauses`

## 4. Templates

- [x] 4.1 `clause_new.html` (extends base): form for section/body/category/province, submit to `/clauses/{type}/new`
- [x] 4.2 `clause_edit.html` (extends base): pre-filled edit form + read-only preview of derived `{{slots}}` and `law_refs`; submit to `/clauses/{type}/clauses/{id}`; delete button posting to `.../delete`
- [x] 4.3 Update `clauses_detail.html`: per-clause edit/delete links + a "新建自定义条款" link to `/clauses/{type}/new`; add a search box posting `q`
- [x] 4.4 Update `clauses_list.html`: add a search box (`q`) in the toolbar

## 5. Public API

- [x] 5.1 Re-export from `src/clauses/__init__.py`: `create_clause`, `update_clause`, `delete_clause`, `search_clauses`

## 6. Tests

- [x] 6.1 `tests/test_clauses_admin_store.py`: `create_clause` (custom -> null source_path + manual=true + body_hash + slot/law derivation); `update_clause` (re-derives body_hash/slots/law_refs, sets manual=true, NotFoundError); `delete_clause` (delete + NotFoundError); `search_clauses` (body/title ILIKE + filter composition); manual-preservation across a simulated re-extract (`delete_auto_clauses` leaves manual rows)
- [x] 6.2 `tests/test_clauses_admin_web.py`: `GET /clauses/{type}/new` 200; `POST` creates a custom clause; `GET /clauses/{type}/clauses/{id}` 200 pre-filled (404 unknown); `POST` update changes body + re-derives; `POST .../delete` removes; `GET /clauses/{type}?q=...` filters by body text
- [x] 6.3 Run `uv run pytest tests/test_clauses_admin_*.py tests/test_clauses_*.py` and confirm all pass (no regression to the read-only suite)

## 7. Verification

- [x] 7.1 `uv run python -c "from src.clauses import create_clause, update_clause, delete_clause, search_clauses; print('imports ok')"`
- [x] 7.2 Manual flow via TestClient: create a custom clause -> edit its body -> verify slots/law_refs re-derived -> delete -> gone; re-extract a source with a manual edit -> manual clause preserved
- [x] 7.3 `uv run uvicorn src.web.app:app --port 8010` -> verify `/clauses`, `/clauses/sale/new`, edit/delete, and `?q=` search render/work
- [x] 7.4 `openspec validate add-clause-admin-dashboard` -> valid
