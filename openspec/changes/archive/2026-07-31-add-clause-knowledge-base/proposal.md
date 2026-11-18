## Why

The repo already ships a slot-based contract generator (`src/contracts/`, 41 skeleton templates + `{{slot}}` placeholders + per-slot `SlotInstruction` with description, rendered to DOCX/PDF via `src/docs/`). But the clause *content* of those templates is a hand-authored skeleton - it does not learn from the **823 real 示范文本** already collected in MinIO (`scraw-law-contracts/contracts/`, provincial-housing/construction-department model contracts, e.g. a 吉林省前期物业服务合同 that cites both 《民法典》 and 《吉林省物业管理条例》).

Two gaps block turning that corpus into reusable knowledge:

1. **The corpus was never ingested.** The Elasticsearch `contracts` index holds only 6 chunks from 4 sample `.md` templates; the 823 `.pdf`/`.docx` contracts live only in MinIO, named by UUID under `contracts/{1,2,3,4,5,None}/`, with **no province in the path**. So the user's premise "elastic 里之前下载的合同文档" does not hold - extraction must read MinIO and infer province from content.
2. **There is no clause knowledge base.** The existing `extract_laws_for_type` only pulls `《...》` law *names* from LLM survey answers; it does not extract reusable contract *clauses* (条款), nor link them to their governing provisions (法条), nor tag them by province.

This change builds that knowledge base: extract structured clauses (each with its `{{slots}}`, slot instructions, cited law references, inferred province, and national/local level) from the 823 示范文本, store them in Postgres under three categories - **base** (national), **tagged** (provincial 特色法条), and **custom** (user-authored) - and generate contracts by assembling base + selected provincial + custom clauses around the existing slot model.

## What Changes

- **New `src/clauses/` package** - the clause knowledge base:
  - `corpus.py` - reads the 823 contracts from MinIO `contracts/` prefix, parses `.docx` (python-docx) / `.pdf` (pypdf) to text. Does **not** depend on Elasticsearch or `llama-index-readers-file`.
  - `extract.py` - per-document LLM extraction (reusing `src/llm.py`) returning structured clauses `{contract_type, section, body (with {{slots}}), slot_instructions, law_refs[], province, level, source_path}`; classifies each doc into one of the 41 contract types; idempotent (stable key = `source_path` + `section` + body hash) so re-runs update rather than duplicate.
  - `store.py` - Postgres `clauses` table (idempotent `CREATE TABLE IF NOT EXISTS` + additive columns, mirroring `src/eval/store.py`); CRUD for base/tagged/custom clauses.
  - `assemble.py` - `generate_contract_assembled(contract_type, *, province=None, custom_clause_ids=None, format="pdf")`: base(type) + tagged(type, province) + custom, ordered by a canonical section order, stitched into a body with `{{slot}}` placeholders kept fillable, rendered via `src/docs`; returns `{docx_path, pdf_path, slots, instructions, law_refs}`.
  - `cli.py` / `__main__.py` - `python -m src.clauses extract [--limit N]` (resumable corpus extraction) and `python -m src.clauses generate <type> [--province 吉林] [--format pdf]`.
- **New web capability** (`src/web/routes/clauses.py` + Jinja templates): `/clauses` browse clauses by contract type / province / category; `/clauses/extract` trigger/schedule extraction; `/clauses/{type}/generate?province=...` assemble + download DOCX/PDF. Wired into `src/web/app.py` alongside the existing `contracts` router.
- **No changes** to `document-generation` (consumed as-is), `contract-templates` (the existing skeleton `generate_contract` stays as the default path; assembly is an additional path), `rag-search` (MinIO is read directly; ES untouched), or scoring/judging.

## Capabilities

### New Capabilities
- `clause-knowledge-base`: extract reusable contract clauses (with linked law references, inferred province, national/local level) from the 823 示范文本 in MinIO; store them in Postgres under base/tagged/custom categories; and assemble a contract from base + provincial-tagged + custom clauses around the existing `{{slot}}` model - exposed as a CLI (`python -m src.clauses`) and a reusable Python API.

### Modified Capabilities
<!-- None. contract-templates is consumed unchanged (slot model + contract_types catalog); document-generation is consumed unchanged; rag-search is untouched. -->

## Impact

- **New code**: `src/clauses/` package (`__init__.py`, `corpus.py`, `extract.py`, `store.py`, `assemble.py`, `cli.py`, `__main__.py`); `scripts/extract_clauses.py` (resumable extraction runner); `src/web/routes/clauses.py`; new templates `clauses_list.html`, `clauses_detail.html`.
- **New tests**: `tests/test_clauses_corpus.py` (MinIO reader + docx/pdf parsing, skipped when MinIO unreachable), `tests/test_clauses_store.py` (clauses table CRUD, category/province/level fields, idempotent upsert), `tests/test_clauses_extract.py` (extraction schema + contract-type classification + province/level inference, stubbed LLM), `tests/test_clauses_assemble.py` (base+tagged+custom assembly, section ordering, slot manifest union, fillable placeholders), `tests/test_clauses_web.py` (routes + generate/download).
- **Modified code**: `src/eval/store.py` `ensure_schema` (add the `clauses` table DDL, idempotent); `src/web/app.py` (include the `clauses` router); `src/web/templates/base.html` (nav link to `/clauses`).
- **Dependencies**: `pypdf` new (pdf text extraction); `python-docx` already present. No `llama-index-readers-file`.
- **Data**: the `clauses` table in the existing `law_bench` Postgres; extracted clause JSON is the source of truth (re-derivable from the corpus, so a bad extraction can be dropped and re-run).
- **Operations**: `python -m src.clauses extract` runs locally and in-container; needs MinIO reachability (`.env` `minio_host` already points at the corpus MinIO) and the `DRAFTER_MODEL` LLM. ~70s/doc LLM call for a full corpus run; resumable via DB-skip + JSON cache.
- **Out of scope**: ingesting the 823 contracts into Elasticsearch for vector RAG (deferred follow-up); in-browser clause editing; auto-drafting via the CrewAI pipeline; mail-merge slot filling.
