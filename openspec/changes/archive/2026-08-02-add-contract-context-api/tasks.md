## 1. Router skeleton + wiring

- [x] 1.1 Create `src/web/routes/contract_context.py` with an `APIRouter(prefix="/api/contracts", tags=["contract-context"])`; add `app.include_router(contract_context.router)` in `src/web/app.py` (top-level, no optional dependency)
- [x] 1.2 Add a response-shaping section in `contract_context.py` (or a small `_shapes.py` alongside it) projecting service-function output into the bundle / slot / clause-catalog shapes; no business logic
- [x] 1.3 Confirm DB-backed endpoints take `db: Path = Depends(get_db)` reusing `src/web/deps.get_db`; `NotFoundError` -> 404 flows through the existing `app.add_exception_handler` in `app.py`

## 2. List + comprehensive bundle

- [x] 2.1 `GET /api/contracts` -> `list_contract_types()` -> `[{key, zh}]`; 200 always (the list is file-backed)
- [x] 2.2 `GET /api/contracts/{contract_type}` -> build the bundle: `get_template` (body+slots), `get_slot_instructions` (+ ontology coverage per D3), `extract_laws_for_type` (refs only, no survey md per D5), `tag_vocab_list` (tags), `SECTION_ORDER` (sections), a clause count summary via `list_clauses` grouped by `source` (base/tagged/custom), the latest-version rubric name for the type (`null` if none), and `list_prompts` filtered to the type (`[{name, purpose}]`); 404 on unknown type
- [x] 2.3 Verify the bundle's `slot_instructions` entries each carry `source` (`registry`/`ontology`/`uncovered`) and that their `name` set equals `template.slots`

## 3. Slot API (focused)

- [x] 3.1 `GET /api/contracts/{contract_type}/slots` -> the same manifest-with-ontology list used in the bundle (D3); reuse the 2.2 shaping helper so the two cannot diverge; 404 on unknown type
- [x] 3.2 Verify a type whose template contains a role-prefixed variant slot (e.g. `seller_address`) returns that slot with `source: "ontology"` and a non-empty `label`/`description`

## 4. Laws + tags (focused)

- [x] 4.1 `GET /api/contracts/{contract_type}/laws` -> `{refs, survey_md}` where `refs = extract_laws_for_type(type)` and `survey_md = get_law_info(type)` projected to `{doubao, deepseek}` (each the markdown string or `null`); 404 on unknown type
- [x] 4.2 `GET /api/contracts/{contract_type}/tags` -> `tag_vocab_list(contract_type)` -> `{dim: [values]}`; 404 on unknown type

## 5. Clause catalog

- [x] 5.1 `GET /api/contracts/{contract_type}/clauses` -> `list_clauses(contract_type=type, tags={scenario,stance} if given, source=source if given)`; apply `limit` (default 50, clamp to 200) / `offset` (default 0); return `{clauses: [...], total: N}` where `total` is the unpaginated match count; each clause row carries `{id, section, source, manual, tags, body}`; 404 on unknown type
- [x] 5.2 Verify `?scenario=农产品买卖&stance=pro_a` filters by the corresponding `tags` dims; verify `?limit=10&offset=0` paginates and `total` reflects the full count

## 6. Generate

- [x] 6.1 `POST /api/contracts/{contract_type}/generate` accepting `{scenario?, stance?, custom_clause_ids?, format}` (`format` default `"docx"`, matching the service default); call `generate_contract_assembled(type, scenario=, stance=, custom_clause_ids=, format=, db=db)`; return `{body_text, slots, instructions, law_refs, diagnostics, docx_url?, pdf_url?}` with `body_text` always present
- [x] 6.2 For `format` in `{docx, pdf, both}`, build download URLs for the written files (serve via a read-only route or static mount under `/api/contracts/{type}/download/<file>`); for `markdown`, `docx_url`/`pdf_url` are `null`
- [x] 6.3 Map `CoherenceError` -> 422 with `{"error": str(exc)}` (register a handler in `app.py` or raise `HTTPException(422, ...)` in-route); map `NotFoundError` -> 404

## 7. Tests

- [x] 7.1 `tests/test_contract_context_api.py`: one test per endpoint - list (200, 43 entries), bundle (200, fields populated), slots (200, ontology coverage), laws (200, refs + survey_md), tags (200, `stance` values), clauses (200, filter + pagination), generate default-docx (200, `docx_url` non-null + `body_text` non-empty), generate markdown (200, `body_text` non-empty, urls null)
- [x] 7.2 Negative tests: unknown `{contract_type}` -> 404 on every endpoint; coherence-failure generate -> 422
- [x] 7.3 Schema test: `GET /openapi.json` includes all seven paths (none excluded via `include_in_schema=False`)
- [x] 7.4 Run `pytest tests/test_contract_context_api.py` and `pytest tests/test_web_app.py` (existing) green

## 8. Docs + deploy

- [x] 8.1 Add a "Contract context API" section to `src/web/README.md` with the endpoint table and an example agent flow (list -> bundle -> generate)
- [ ] 8.2 Deploy: merge to main (CI builds `sha-<short>`), bump `deploy/deployment.yaml` image tag, commit, let ArgoCD selfHeal; verify `http://23.144.68.246:30820/api/docs` shows the new paths and `GET /api/contracts/sale` returns a 200 bundle
