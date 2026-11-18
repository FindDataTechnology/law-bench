## Context

Two existing assets are relevant:

1. **A slot-based contract generator** (`src/contracts/`, added by the complete `add-contract-generation-web` change): 41 skeleton templates (`src/contracts/data/contracts.json`, keyed by `output/law_info/contract_types.json`), each a Markdown `body` with `{{slot}}` placeholders plus a `slot_instructions` manifest (`{name, label, description, example, required}`). `generate_contract(type, *, format)` renders the body to DOCX/PDF via `src/docs/` with slots left as highlighted fillable placeholders. `extract_laws_for_type(type)` pulls `《...》` law *names* from Doubao+DeepSeek survey answers - law names only, not clause text.
2. **A contract corpus in MinIO** (`scraw-law-contracts/contracts/`, 823 `.pdf`+`.docx` 示范文本 - provincial department model contracts). Confirmed by inspection: filenames are UUIDs under `contracts/{1,2,3,4,5,None}/` (367/100/154/107/92/3); **province is not in the path** (a 吉林省 contract sits in `1/`). The Elasticsearch `contracts` index holds only 6 chunks from 4 sample `.md` templates - the 823 contracts were **never ingested**, and pdf/docx ingest needs `llama-index-readers-file` (not installed). A sampled contract (吉林省前期物业服务合同) shows province is cleanly inferable from content: title, issuing authority (吉林省住建厅+市场监管厅), and local regulations (《吉林省物业管理条例》) alongside national ones (《民法典》《物业管理条例》).

Infra: Postgres is the relational store (`src/eval/db.py` `connect()`, DSN `database_url` -> `23.144.68.246:15432/law_bench`); `src/eval/store.py` `ensure_schema` is the idempotent schema pattern (CREATE TABLE IF NOT EXISTS + additive ALTER columns, memoized per-DB). MinIO config lives in `src/settings.py` (`minio_host`, `minio_root_user`, `minio_root_password`, `MINIO_BUCKET`). The LLM is wired in `src/llm.py` (`DRAFTER_MODEL`). Constraints: runs locally (macOS) and in the Linux/k3s container; minimize new dependencies.

## Goals / Non-Goals

**Goals:**
- Read the 823 示范文本 from MinIO `contracts/` and parse `.docx`/`.pdf` to text **without** ES or `llama-index-readers-file`.
- Per document, LLM-extract structured clauses - each with `contract_type` (one of the 41), `section`, `body` (containing `{{slot}}` placeholders), `slot_instructions`, `law_refs[]`, inferred `province`, and `level` (national/local) - and store them in a Postgres `clauses` table under three categories: **base** (national), **tagged** (provincial), **custom** (user-authored).
- Assemble a contract from base(type) + tagged(type, province) + custom clauses, ordered by a canonical section order, keeping `{{slots}}` fillable, rendered to DOCX/PDF via `src/docs` - an additional generation path alongside the existing skeleton `generate_contract`.
- Expose extraction + assembly on the web (`/clauses*`).

**Non-Goals:**
- Ingesting the 823 contracts into Elasticsearch for vector RAG (deferred).
- Modifying `contract-templates` (the skeleton path stays the default), `document-generation`, or `rag-search`.
- Auto-drafting via CrewAI; in-browser clause editing; slot mail-merge; bespoke legal prose authoring beyond what the corpus supplies.

## Decisions

### D1: Extraction unit = contract clause (条款) with linked law references (法条)
**Choice**: The extracted unit is a reusable contract clause. Each clause carries `law_refs[]` (the 《...》 provisions it relies on, reusing `src.eval.legal_refs` categorization) - so clauses are the assembly material and law references are their "依据". This is option C from the design exploration.
**Rationale**: The DB categories are 基本条款/标签条款/自定义条款 and the purpose is "以此为依据生成合同" - the unit must be clause text that gets assembled, with law refs as linked evidence. The existing `extract_laws_for_type` (law names only) stays for the skeleton path; it is not reused for clause bodies.
**Alternatives**: (A) pure clauses without law refs - loses the "依据" link; (B) extract statutory article text only - does not produce assembleable contract prose. Rejected.

### D2: One `clauses` table, three categories via a `category` column
**Choice**: A single `clauses` table with `category ∈ {base, tagged, custom}`. `base` = clauses from national-level 示范文本 (per contract_type). `tagged` = clauses from provincial 示范文本 (`province` set) - the 特色法条. `custom` = user-authored (`source_path` null).
**Rationale**: Three categories are a label on the same shape of record, not three shapes. One table keeps queries (assemble base+tagged+custom for a type/province) simple and mirrors the `law_info` table pattern.
**Alternatives**: Three tables - rejected, forces a UNION on every assembly.

### D3: Province and level are inferred from content by the extraction LLM; the MinIO `1-5/None` dirs are NOT used as labels
**Choice**: The extraction prompt reads the contract text and emits `province` (e.g. "吉林", or null) and `level` ("national" | "local"). `level=national` when the doc has no provincial issuing authority **and** references only national-level laws; otherwise `level=local` with `province` = the inferred province. The `1-5/None` top-level dirs are preserved in `source_path` for provenance only.
**Rationale**: Confirmed by inspection that province is absent from paths but richly present in content (title, issuer, local regs); the dirs are an unknown upstream bucketing (a 吉林 contract is in `1/`), unsafe to treat as province or type.
**Alternatives**: Treat `1-5` as a pre-label - rejected (verified misleading). Hand-rule province from filename - impossible (UUIDs).

### D4: New corpus reader in `src/clauses/`, parsing with python-docx + pypdf (no ES, no llama-index-readers-file)
**Choice**: `corpus.py` lists `contracts/` objects via the MinIO client (reusing `src/settings` MinIO config + the `NO_PROXY=*` boto3 workaround from `src/search/minio_source.py`), downloads each object to a temp file, and extracts text with `python-docx` (`.docx`) or `pypdf` (`.pdf`). Each parsed doc carries `source_path`, `object_name`, and the raw text.
**Rationale**: The corpus is structured extraction input, not a vector search corpus; ES is unnecessary for v1. `llama-index-readers-file` is not installed and would add weight; python-docx is already present and pypdf is a single light dep. `.docx`/`.pdf` pairs share a UUID - parse `.docx` when available (cleaner text), fall back to `.pdf`.
**Alternatives**: Reuse `src/search/minio_source.load_documents` - rejected (it pulls `templates/`+`drafts/` by default and needs the uninstalled file extractors). Ingest into ES first - rejected for v1 (deferred).

### D5: Extraction is an LLM pipeline, idempotent and resumable
**Choice**: `extract.py` calls the `DRAFTER_MODEL` LLM (via `src/llm.py`) once per document, returning a list of clauses conforming to a strict JSON schema (contract_type, section, body, slot_instructions, law_refs, province, level). Idempotency key = `(source_path, section, md5(body))`; re-running a document deletes its existing clauses then re-inserts (mirrors `src/search/ingest.py`'s delete-then-insert). Raw extracted JSON is cached under `src/clauses/data/_extracted/<uuid>.json` so re-runs without LLM cost are possible. The runner skips `source_path`s already extracted unless `--force`.
**Rationale**: ~823 LLM calls must be resumable (network/LLM failures mid-run) and re-runnable (prompt tweaks). A strict schema prevents inconsistent clause splitting. Caching decouples extraction from DB loading.
**Alternatives**: One LLM call per clause - rejected (823×N calls, too costly). No idempotency - rejected (re-runs duplicate).

### D6: Generation augments the skeleton; assembly is a new path, slots stay fillable
**Choice**: New `generate_contract_assembled(contract_type, *, province=None, custom_clause_ids=None, format="pdf", out_dir=None)` selects base(type) + tagged(type, province) + custom(ids), orders them by a canonical `SECTION_ORDER` (parties, recitals, subject, rights/obligations, term, payment, breach, dispute, governing law, signatures - aligned to the skeleton's section headings), concatenates clause bodies into one Markdown body, and renders via `src/docs.create_docx` with `slots=None` (every `{{slot}}` stays a highlighted fillable placeholder). The returned `instructions` is the union of the 12 canonical `SlotInstruction`s (from `src/contracts/slots.py`) plus any clause-declared slots; `law_refs` is the deduped union. The existing `generate_contract` (skeleton) is unchanged and remains the default.
**Rationale**: Decision (b) from exploration - keep the proven slot model + skeleton as default; the clause DB provides selectable clause *content* per section, and clauses may declare slots beyond the 12 canonical (e.g. `property_name` for 物业服务). `slots=None` preserves the "fillable template, not filled contract" guarantee from `contract-templates`.
**Alternatives**: Replace the skeleton entirely - rejected (riskier; loses a working default). Pre-fill slots - rejected (deliverable is a fillable template).

### D7: New `src/clauses/` package + `/clauses` web routes; reuse `contract-templates` slot model + `document-generation` renderer
**Choice**: `src/clauses/` owns corpus reading, extraction, the `clauses` table, and assembly. It imports `SlotInstruction` / `REQUIRED_SLOTS` / `default_slot_instructions` from `src/contracts/slots.py` and `list_contract_types` from `src/contracts/templates.py`, and renders via `src/docs`. Web: `/clauses` (browse by type/province/category), `/clauses/extract` (trigger resumable extraction), `/clauses/{type}/generate?province=...&format=...` (assemble + `FileResponse`), wired into `src/web/app.py` like the `contracts` router.
**Rationale**: Clauses are a distinct capability but build on the existing slot + contract-type + doc-rendering primitives; reusing them avoids divergence (the same lesson as `contract-templates` reusing `document-generation`).
**Alternatives**: Fold into `src/contracts/` - rejected (mixes skeleton generation with corpus-driven knowledge, different lifecycles).

### D8: `clauses` table in the existing `law_bench` Postgres; `ensure_schema` extended idempotently
**Choice**: DDL added to `src/eval/store.py` `ensure_schema`:
```
CREATE TABLE IF NOT EXISTS clauses (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    contract_type   TEXT NOT NULL,
    category        TEXT NOT NULL CHECK (category IN ('base','tagged','custom')),
    section         TEXT NOT NULL,
    body            TEXT NOT NULL,
    slot_instructions JSONB NOT NULL DEFAULT '[]'::jsonb,
    law_refs        JSONB NOT NULL DEFAULT '[]'::jsonb,
    province        TEXT,
    level           TEXT CHECK (level IN ('national','local')),
    source_path     TEXT,
    source_doc_title TEXT,
    body_hash       TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
```
`category='custom'` implies `source_path IS NULL`; `category='tagged'` implies `province IS NOT NULL`. Idempotent upsert keyed on `(source_path, section, body_hash)` for base/tagged; custom rows are managed by id.
**Rationale**: Same Postgres, same `ensure_schema` memoization pattern, same `_BorrowedConn` connection model as `law_info`. `CHECK` constraints encode the category semantics; `body_hash` enables idempotent re-extraction.
**Alternatives**: A separate DB - rejected (one more connection to manage).

## Risks / Trade-offs

- **[Contract-type classification]** The 823 docs are not pre-labeled with one of the 41 types; the extraction LLM must classify each. Misclassification drops a clause into the wrong type bucket. Mitigation: the prompt constrains output to the 41 keys or `"unknown"`; `unknown` clauses are stored but excluded from assembly until relabeled. Flagged as an open question.
- **[Province inference errors]** LLM may misread issuer/local regs. Mitigation: store the raw signals (`source_doc_title`, `law_refs`) for audit; ambiguous docs default to `level=national` with `province=null` (conservative - they contribute to base, not a wrong province).
- **[Clause splitting inconsistency]** LLMs vary clause boundaries across docs. Mitigation: strict schema + `section` normalized to the canonical `SECTION_ORDER` vocabulary; a clause with an unrecognized section is still stored (section as-is) but sorted last.
- **[pdf/docx parsing noise]** Tables, headers, watermarks in 示范文本. Mitigation: prefer `.docx` (cleaner paragraphs); strip boilerplate (使用说明, 编号 blanks); cap chunk size passed to the LLM.
- **[MinIO endpoint]** Resolved during implementation: the `.env` `minio_host=http://23.144.68.246:30900` points at the `minio`-namespace MinIO which **does** hold `scraw-law-contracts` (the `law-craw-web` MinIO is ClusterIP-only, so `:30900` is unambiguously the corpus instance). `corpus.py` reuses `src.settings` MinIO config directly; no separate `contracts_minio_host` setting was needed.
- **[Extraction cost]** ~823 LLM calls. Mitigation: resumable runner + JSON cache; run a `--limit 20` sample first to validate the schema/prompts before the full run.
- **[Remote Postgres RTT]** ~0.22s/query (per memory). Acceptable for batch seeding; `ensure_schema` is memoized.

## Migration Plan

1. Add `src/clauses/` package (`__init__.py`, `corpus.py`, `extract.py`, `store.py`, `assemble.py`, `cli.py`, `__main__.py`).
2. Add the `clauses` DDL to `src/eval/store.py` `ensure_schema`; add `contracts_minio_host` to `src/settings.py`.
3. Implement `corpus.py` + `extract.py` + `store.py`; run `python -m src.clauses extract --limit 20` against a sample; validate extracted clause shape + province/level on the 吉林 sample.
4. Implement `assemble.py` + `cli.py`; verify `python -m src.clauses generate property_service --province 吉林 --format pdf` assembles base+tagged+custom and renders fillable slots.
5. Add `src/web/routes/clauses.py` + templates; wire into `src/web/app.py` + `base.html` nav.
6. Add tests; run `openspec validate add-clause-knowledge-base`.
7. Run the full `python -m src.clauses extract` over the 823 corpus (resumable).
8. **Rollback**: drop `src/clauses/`, `src/web/routes/clauses.py`, the templates, the `base.html`/`app.py` edits, and the `clauses` table (`DROP TABLE clauses`). No existing route or the skeleton `generate_contract` is affected.

## Open Questions

- **`1-5/None` dirs**: what is this upstream bucketing (contract-type cluster? quality tier? source batch)? Ignored as a label (province inferred from content); the sample run showed no obvious mapping to type or province.
- **MinIO endpoint**: resolved - `.env` `minio_host=:30900` is the `minio`-namespace MinIO with the corpus; no new setting needed.
- **Contract-type classification**: auto-classify into the 41 types with an `"unknown"` escape hatch, or require manual relabeling? (Leaning: auto + unknown.)
- **Province confidence**: is a review queue needed for low-confidence province inferences, or is "default to national" enough for v1? (Leaning: default-to-national for v1.)
- **ES RAG follow-up**: ingest the 823 into ES as a recall fallback when extraction misses a clause? Deferred.
