## 1. Setup

- [x] 1.1 Create the `src/clauses/` package with an empty `__init__.py`
- [x] 1.2 ~~Add `contracts_minio_host` to `src/settings.py`~~ — **deviated**: the existing `.env` `minio_host=http://23.144.68.246:30900` already points at the `minio`-namespace MinIO that holds `scraw-law-contracts` (the `law-craw-web` MinIO is ClusterIP-only). No new setting needed; `corpus.py` reuses `src.settings` MinIO config.
- [x] 1.3 Add `pypdf` to `pyproject.toml` dependencies and `uv sync`

## 2. Corpus reader

- [x] 2.1 Implement `src/clauses/corpus.py`: `list_corpus_documents(prefix="contracts/")` returning `[{object_name, source_path, ext}]` from the `scraw-law-contracts` bucket via the MinIO client (reuse `src/settings` MinIO creds + `NO_PROXY=*` workaround from `src/search/minio_source.py`)
- [x] 2.2 Implement `read_document(object_name)` downloading to a temp file and extracting text: `.docx` via `python-docx` (paragraphs + table cells), `.pdf` via `pypdf`; prefer `.docx` when a `.docx`/`.pdf` UUID pair exists (`iter_unique_documents`); return `{source_path, ext, text}`
- [x] 2.3 Strip boilerplate (使用说明, blank 合同编号 lines) from extracted text; collapse whitespace runs
- [x] 2.4 `ConfigError` on unreachable MinIO (no silent empty list)

## 3. Extraction pipeline

- [x] 3.1 Define the clause JSON schema in `src/clauses/extract.py`: `{contract_type, section, body, slot_instructions:[{name,label,description,example,required}], law_refs:[{name,category,category_zh}], province, level, source_path}`; `contract_type` constrained to the 41 keys or `"unknown"`
- [x] 3.2 Implement `extract_document(document)` calling `DRAFTER_MODEL` via `litellm` once per document, returning clauses conforming to the schema; `section` mapped to the canonical `SECTION_ORDER` vocabulary
- [x] 3.3 Compute `body_hash = md5(body)`; `_normalize_slot_instructions` ensures `slot_instructions` covers every `{{slot}}` in `body` (reuses `src.docs.SLOT_PATTERN`); drop clauses with empty `body`
- [x] 3.4 Cache raw extracted JSON to `src/clauses/data/_extracted/<stem>.json` so re-runs can skip LLM cost
- [x] 3.5 Province/level inference per D3: `level=national` when no provincial issuer and only national laws; else `level=local` + `province`; ambiguous -> national + null province. `category` derived (`tagged` if local, else `base`).

## 4. Clause storage

- [x] 4.1 Add the `clauses` table DDL (D8) to `src/eval/store.py` `ensure_schema` (idempotent `CREATE TABLE IF NOT EXISTS` + `CHECK` constraints + partial unique index `(source_path, section, body_hash)`); also added `clauses` to `tests/conftest.py` `_ALL_TABLES` for test isolation
- [x] 4.2 Implement `src/clauses/store.py`: `upsert_clause`, `upsert_clauses`, `delete_clauses`, `list_clauses`, `get_custom_clause`, `list_extracted_source_paths`, `count_clauses`, `counts_by_type`; idempotent upsert via `ON CONFLICT`; reuse `src.eval.db.connect`
- [x] 4.3 Enforce category semantics in `_row`: `custom` -> `source_path` null; `base` -> `province` null + `level=national`; `tagged` -> `level=local`

## 5. Extraction runner

- [x] 5.1 Implement `python -m src.clauses extract` (+ `scripts/extract_clauses.py`): iterate `iter_unique_documents()`, skip `source_path`s in `list_extracted_source_paths()` unless `--force`, parse + `extract_document` + `delete_clauses` then `upsert_clauses`; `--limit N`; per-doc errors non-fatal
- [x] 5.2 Ran `python -m src.clauses extract --limit 15`; validated real docs: 云南 tourism_service (local/云南), 辽宁 real_estate_sale, 江西 sale, national brokerage (base) — province/level/contract_type all correct
- [ ] 5.3 Full `python -m src.clauses extract` over all 601 unique docs — **deferred**: ~70s/doc LLM cost; resumable via cache + DB skip. Run as a background job when ready.

## 6. Assembly generator

- [x] 6.1 Define `SECTION_ORDER` in `src/clauses/extract.py` (当事人, 鉴于, 合同标的, 价款及支付, 履行期限, 权利义务, 违约责任, 争议解决, 附则, 签署信息)
- [x] 6.2 Implement `generate_contract_assembled(contract_type, *, province=None, custom_clause_ids=None, format="pdf", out_dir=None, db=None)`: select base(type) + tagged(type, province) + custom(ids), order by `SECTION_ORDER`, group bodies by section
- [x] 6.3 Render via `src.docs.create_docx(body, <out>, title=zh_name)` with `slots=None` (fillable placeholders); `docx_to_pdf` for pdf/both; return `{docx_path, pdf_path, slots, instructions, law_refs}` where `instructions` = union of the 12 canonical `SlotInstruction`s + clause-declared slots, `law_refs` = deduped union; raise `NotFoundError` for unknown type
- [x] 6.4 Verified `find_slots` on the generated DOCX matches the returned `instructions` set (slots stay literal `{{...}}` fillable placeholders)

## 7. CLI

- [x] 7.1 Implement `src/clauses/cli.py` (argparse): `extract [--limit N] [--force] [--prefix]`, `generate <type> [--province] [--custom] [--format] [--out]`, `stats`; print paths on success; exit non-zero + name the type on `NotFoundError`
- [x] 7.2 Add `src/clauses/__main__.py` invoking `cli.main()`

## 8. Web exposure

- [x] 8.1 Implement `src/web/routes/clauses.py` (APIRouter, `tags=["clauses"]`): `GET /clauses`, `POST /clauses/extract`, `GET /clauses/{type}/generate?province=...&format=...` (assemble + `FileResponse`; 404 unknown type, 400 bad format), `GET /clauses/{type}` (browse clauses by section with province/category filters)
- [x] 8.2 Create `src/web/templates/clauses_list.html` + `clauses_detail.html` extending `base.html`
- [x] 8.3 Wire the `clauses` router into `src/web/app.py` via the lazy-include block; add a `/clauses` nav link (条款库) in `src/web/templates/base.html`

## 9. Public API

- [x] 9.1 Re-export from `src/clauses/__init__.py`: `list_corpus_documents`, `iter_unique_documents`, `read_document`, `extract_document`, `extract_clauses`, `list_clauses`, `upsert_clause`, `upsert_clauses`, `delete_clauses`, `get_custom_clause`, `count_clauses`, `counts_by_type`, `list_extracted_source_paths`, `generate_contract_assembled`, `SECTION_ORDER`, `section_rank`

## 10. Tests

- [x] 10.1 `tests/test_clauses_corpus.py`: `_clean` boilerplate strip; `_parse_docx` local file; `list_corpus_documents` raises `ConfigError` when MinIO unreachable; real-MinIO integration test (skip if unreachable)
- [x] 10.2 `tests/test_clauses_store.py`: `clauses` table CRUD; category/province/level semantics (custom->null source_path, tagged->province set + local, base->national + null province); idempotent upsert; `list_clauses` filtering + section ordering; `counts_by_type`/`count_clauses`
- [x] 10.3 `tests/test_clauses_extract.py`: `_post_process` (national->base, local->tagged, unknown type normalization, default level from province); `_normalize_slot_instructions` (adds missing, drops extra); `_law_refs_from_body` categorizes 《...》; `extract_document` with stubbed LLM; empty text skips LLM
- [x] 10.4 `tests/test_clauses_assemble.py`: base-only / with-province / with-custom assembly; `SECTION_ORDER` ordering; `instructions` = canonical ∪ clause-declared slots; slots stay fillable; `NotFoundError` for unknown type; `ValueError` for bad format; PDF test skips when `soffice` absent
- [x] 10.5 `tests/test_clauses_web.py`: `GET /clauses` lists types; `GET /clauses/sale` shows clauses; `GET /clauses/sale/generate?format=docx` streams a docx; unknown type -> 404; bad format -> 400
- [x] 10.6 Ran `uv run pytest tests/test_clauses_*.py` — 31 passed, 1 skipped (PDF/soffice)

## 11. Verification

- [x] 11.1 `uv run python -c "from src.clauses import list_corpus_documents, extract_clauses, list_clauses, generate_contract_assembled; print('imports ok')"`
- [x] 11.2 `python -m src.clauses extract --limit 15` then `generate_contract_assembled('brokerage', format='docx')` + `('sale', province='吉林', format='docx')` -> files created, fillable slots, instructions + law_refs populated
- [x] 11.3 `TestClient` verified `/clauses` (200), `/clauses/sale`, `/clauses/sale/generate?format=docx`, unknown->404, bad format->400
- [x] 11.4 `openspec validate add-clause-knowledge-base` -> valid
