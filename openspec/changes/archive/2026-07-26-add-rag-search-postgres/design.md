## Context

The project is a Chinese legal contract drafter (CrewAI + Volcengine Ark) with a FastAPI evaluation-rules web app. Two structural gaps motivate this change:

1. **No retrieval.** Drafting uses only the fixed seed templates under `templates/`. There is no way to search prior generated drafts or template clauses by meaning. The user wants LlamaIndex-based semantic search over the contract corpus (templates + generated drafts), exposed both as a web search API/page and as a CrewAI RAG tool the drafter can call.

2. **SQLite-locked data layer.** The entire relational layer (`rubrics`, `criteria`, `prompts`, `eval_runs`, `eval_criteria_results`, `compare_runs`) lives in one local SQLite file (`db/evaluation_rules.db`), mandated at the spec level. Every CRUD/store function takes `db_path: Path`, opens `sqlite3.connect()`, and uses SQLite-specific SQL (`?` placeholders, `AUTOINCREMENT`, `PRAGMA table_info`, `lastrowid`). The web seam `get_db() -> Path` is also the test-injection point (tests override it with a temp file). The user wants a **full swap to PostgreSQL** (`database_url`).

External services are already provisioned in `.env` (some with placeholder passwords): Elasticsearch at `23.144.68.246:30920`, MinIO at `23.144.68.246:30900`, and a Postgres DSN `postgresql://app:...@localhost:5432/law_bentch`. An `OPENROUTER_API_KEY` must be added.

The user's locked decisions (from exploration): index own templates + drafts (1a); search both as API/UI and as a CrewAI RAG tool (2c); embedding = `nvidia/nemotron-3-embed-1b:free` via OpenRouter (3); full SQLite->Postgres swap (4).

## Goals / Non-Goals

**Goals:**
- Add a LlamaIndex search subsystem: read docs from MinIO, chunk, embed via OpenRouter (`nvidia/nemotron-3-embed-1b:free`, 2048-dim), store in Elasticsearch, and serve ranked retrieval via `/api/search` + `/search` and a CrewAI tool.
- Migrate the evaluation data layer from SQLite to PostgreSQL, preserving table/column/constraint shape and all existing API/route behavior.
- Preserve test hermeticity: no external network/LLM; MinIO/ES/OpenRouter faked; tests run against a local throwaway Postgres.
- Keep the storage swap transparent to `/api/*` callers (response shapes unchanged).

**Non-Goals:**
- No hybrid (dense+sparse) retrieval, no reranker, no query rewriting - dense cosine search only for v1. (bge-m3's hybrid mode is out of scope since the chosen model is nemotron-3-embed-1b.)
- No ORM introduction. The hand-written SQL is translated to Postgres dialect, not rewritten behind SQLAlchemy.
- No multi-tenant search; one corpus, one ES index.
- No migration of the existing `output/*.md` drafts into MinIO automatically in this change - ingestion reads whatever is in MinIO; a separate one-time upload step is assumed. (Tracked as an open question.)
- No change to the Ark LLM roles (intake/drafter/auditor) - only the drafter gains an optional retrieval tool.

## Decisions

### Decision 1: Embedding = `nvidia/nemotron-3-embed-1b:free` via OpenRouter, 2048 dims
Use OpenRouter's OpenAI-compatible `/api/v1/embeddings` endpoint with `nvidia/nemotron-3-embed-1b:free` (a 34-language multilingual model, #1 at the 1B scale on RTEB, L2-normalized 2048-dim output). Implemented with LlamaIndex `OpenAILikeEmbedding(api_base=..., api_key=$OPENROUTER_API_KEY, model_name="nvidia/nemotron-3-embed-1b:free")`. The 2048 dimension is verified from NVIDIA's model card and locked into the ES `dense_vector` mapping.

**Alternatives considered:**
- *`baai/bge-m3` ($0.01/M, 1024-dim)*: better Chinese-specialization + hybrid retrieval; rejected because the user explicitly chose the free OpenRouter model. (bge-m3 remains the recommended swap if Chinese retrieval quality is later found insufficient - see Open Questions.)
- *Self-host bge-m3 locally (Ollama/TEI, CPU)*: genuinely $0 + best Chinese; rejected - adds a local inference service to operate, leaving OpenRouter which the user asked to use.
- *Ark `doubao-embedding-*`*: already-paid key, OpenAI-compatible; rejected for the same "use OpenRouter free" reason.

### Decision 2: ElasticsearchStore with `dense_vector` dims=2048, cosine; dimension-mismatch guard
Use `llama_index.vector_stores.elasticsearch.ElasticsearchStore(index_name=..., es_url=..., es_user=..., es_password=...)` with `VectorStoreIndex.from_vector_store(...)`. The ES index mapping declares `dense_vector` with `dims: 2048` and `similarity: cosine` (model output is L2-normalized, so cosine == dot-product). A startup check compares the configured dims against the existing index mapping and refuses to write on mismatch, requiring an explicit reindex.

**Alternatives considered:**
- *`dot_product` similarity*: equivalent given L2-normalization; cosine is the LlamaIndex ES default and clearer to readers.
- *`int8` quantization*: storage/perf win at scale; deferred - the corpus is small.

### Decision 3: Storage swap = `sqlite3` -> `psycopg3`, hand-written SQL translated (no ORM)
Replace `sqlite3` with `psycopg` (psycopg3, `psycopg[binary]`) across `src/eval/{db,store,prompt_crud,rubric_crud,harbor_seed}.py`. Translate dialect mechanically: `?`->`%s`, `INTEGER PRIMARY KEY AUTOINCREMENT`->`BIGINT GENERATED ALWAYS AS IDENTITY`, `cur.lastrowid`->`INSERT ... RETURNING id`, `PRAGMA foreign_keys=ON` removed (on by default in PG), `PRAGMA table_info`/`sqlite_master`->`information_schema.columns`/`information_schema.tables`, `conn.executescript`-> per-statement `execute` or `execute` with multiple statements. Row access uses `psycopg.rows.dict_row` (replacing `sqlite3.Row`).

**Alternatives considered:**
- *SQLAlchemy ORM*: rejected - large refactor of a deliberately hand-SQL codebase, and the user asked for a swap not a rewrite.
- *Backend abstraction (SQLite + Postgres impls, keep SQLite for tests)*: rejected - the user explicitly chose a **full swap**, and a dual backend doubles the SQL surface to maintain.

### Decision 4: `get_db()` seam returns a connection, not a `Path`
`src/web/deps.py::get_db()` changes from `-> Path` to `-> Connection` (or a small connection-pool/session wrapper). The `db_path: Path` parameter threaded through every CRUD/store function becomes a `conn`/`session` parameter. This is the single mechanical ripple of the swap and the test-injection point.

**Alternatives considered:**
- *Keep `db_path` and resolve DSN internally*: rejected - a `Path` cannot represent a network DSN; the seam must change type.
- *Per-call `psycopg.connect(database_url)`*: rejected for prod (no pooling); use a module-level connection pool or a request-scoped connection via the dependency.

### Decision 5: Test posture = session-scoped local Postgres + per-test transaction rollback (or per-test schema)
Tests run against a local Postgres (resolved from a test DSN, e.g. `TEST_DATABASE_URL` or a `postgresql://.../test_law_bench`), with per-test isolation via either transaction-rollback (begin a transaction per test, roll back at teardown) or a per-test schema. This preserves hermeticity (no external network - Postgres is local; no LLM; MinIO/ES/OpenRouter faked) and is fast (no per-test server start). `tests/conftest.py` fixtures yield a connection to a throwaway-isolated database.

**Alternatives considered:**
- *testcontainers-python*: hermetic and realistic, but adds a Docker dependency to CI/local runs and is slow to start per test.
- *Embedded Postgres (`pg_embedded`/`postgresql-binaries`)*: no Docker, best hermeticity, but adds a binary-download dependency; viable fallback if a local Postgres is unavailable in CI.
- *Keep SQLite for tests only*: explicitly rejected by the full-swap decision - it would mean maintaining two SQL dialects in the data layer.

### Decision 6: Chunking = section-by-markdown-header + size cap
Contract markdown is structured by headings (`#`/`##`). Chunk by header section (each `##` clause becomes a chunk), with a `SentenceSplitter` fallback that splits over-long sections and merges tiny ones into a target size range. Preserve the section heading and the source path as chunk metadata.

**Alternatives considered:**
- *Fixed-size `SentenceSplitter` only*: simpler, but splits clauses mid-sentence and loses structural meaning that matters for legal text.
- *Per-paragraph*: contracts are not reliably paragraph-delimited; header-sectioning matches the document's own structure.

### Decision 7: RAG tool = a CrewAI `BaseTool` on the drafter, env-toggleable, graceful degradation
Register a retrieval tool (`src/search/rag_tool.py`) the drafter agent can call. Toggle with `RAG_TOOL_ENABLED` (default on). On any backend failure (ES/OpenRouter/MinIO unreachable), the tool returns an empty context string and the drafter proceeds - it never propagates an exception to the crew. Retrieval is a *tool call* (the agent decides when to retrieve) rather than always-on injected context, so a drafting request that needs no precedent pays no retrieval cost.

**Alternatives considered:**
- *Always-on: pre-fetch top-k chunks into the drafter task input*: simpler but always pays the embedding+search cost and always injects possibly-irrelevant context.
- *Retrieval as a separate crew task/agent*: heavier; a tool keeps the crew shape unchanged.

### Decision 8: New code under `src/search/`; route under `src/web/routes/search.py`
New `src/search/` package: `minio_source.py` (reader/config), `embeddings.py` (OpenRouter client + dims), `vector_store.py` (ES wiring + mismatch guard), `ingest.py` (pipeline + CLI), `query.py` (LlamaIndex query engine), `rag_tool.py` (CrewAI tool), `config.py` (env→settings). New web route module `src/web/routes/search.py` adds `/api/search` + `/search`, wired into `create_app()` alongside the existing `api`/`pages` routers. A `/search.html` template is added under `src/web/templates/`.

**Alternatives considered:**
- *Put search code under `src/eval/`*: rejected - search is a distinct concern from evaluation rules; a separate package keeps boundaries clean.

### Decision 9: One-time data migration = idempotent SQLite->Postgres copy script
Add `scripts/migrate_sqlite_to_postgres.py` that reads the existing `db/evaluation_rules.db` and upserts rows into Postgres, keyed on natural keys (rubric `name`+`source`, criterion `rubric_id`+`name`, prompt `name`, etc.). Harbor seed + per-class seeders already upsert idempotently, so the migration can also simply re-run the seeders against Postgres - the copy script is a belt-and-suspenders path for `eval_runs`/`compare_runs` (which are not re-seeded). The `db/evaluation_rules.db` file is left in place (not deleted) until the swap is verified.

**Alternatives considered:**
- *Dump/restore via SQL*: SQLite and Postgres dialects differ enough (AUTOINCREMENT, types) that a direct dump is fragile; a row-level copy is clearer.

## Risks / Trade-offs

- **[Storage swap is cross-cutting and breaks the test seam]** -> *Mitigation:* Decision 3 (mechanical dialect translation) + Decision 5 (Postgres test fixture) bound the blast radius; the data-layer tests already pin behavior, so a green suite proves equivalence. Roll back via git + keeping the SQLite file.
- **[External service dependencies must be verified before coding]** -> *Mitigation:* pre-implementation spikes (see Open Questions): confirm ES version/KNN at `:30920` + real password; one OpenRouter embed call returns a 2048-dim vector; MinIO reachable with the configured credentials; Postgres `database_url` reachable with a real password.
- **[`:free` embedding rate limits / availability]** -> *Mitigation:* ingestion is batched with backoff and per-chunk failure isolation (rag-search spec); the `:free` model may be intermittently unavailable - ingestion is re-runnable and not on the hot path.
- **[Embedding dims (2048) lock the ES index]** -> *Mitigation:* dimension-mismatch guard (Decision 2); swapping the model requires an explicit reindex, documented in the spec.
- **[Chinese retrieval quality with an English-leaning free model]** -> *Accepted trade-off:* nemotron-3-embed-1b is 34-language multilingual and RTEB #1 at 1B; it handles Chinese but is not China-specialized. If retrieval quality is insufficient, swap to `baai/bge-m3` ($0.01/M) + reindex - a documented, cheap fallback.
- **[Postgres not yet provisioned / placeholder passwords]** -> *Mitigation:* provisioning is a prerequisite task; real `database_url` + ES password + `OPENROUTER_API_KEY` must be set before implementation.
- **[Existing generated drafts not yet in MinIO]** -> *Mitigation:* ingestion reads from MinIO; a one-time upload of `templates/*.md` and `output/*.md` into the bucket is a prerequisite (Open Question).

## Migration Plan

1. **Provision + verify** external services: real Postgres DSN + password; ES version ≥8.x + real password; `OPENROUTER_API_KEY`; MinIO bucket `contracts` with `templates/` + `drafts/` populated. (Prerequisite tasks; some may require the user.)
2. **Storage swap** (`src/eval/*`, `src/web/deps.py`, `src/settings.py`): psycopg3, dialect translation, `get_db`->connection. Keep `db/evaluation_rules.db` in place.
3. **Migrate data**: run `scripts/migrate_sqlite_to_postgres.py` (or re-run seeders against Postgres for rubrics/criteria/prompts; copy `eval_runs`/`compare_runs`).
4. **RAG subsystem** (`src/search/*`): MinIO source, embeddings, ES store, ingest CLI, query engine, CrewAI tool. Wire `/api/search` + `/search` route.
5. **Tests**: port the suite to the Postgres fixture; add search tests with faked backends.
6. **Verify**: run ingestion over the bucket; confirm 2048-dim vectors in ES; exercise `/api/search` with a Chinese query; confirm a drafting run uses the RAG tool and degrades gracefully with the backend down.

**Rollback:** the RAG subsystem is additive and isolated - revert `src/search/` + the route. The storage swap is the irreversible-ish part; keep `db/evaluation_rules.db` and the old `get_db`-returns-Path code reachable via git until the Postgres path is verified in prod.

## Open Questions

1. **ES version + KNN at `:30920`** - confirm the cluster is 8.x with `dense_vector`/knn enabled and the real `elastic` password. (Spike before implementation.)
2. **OpenRouter pass-through of nemotron** - make one `/api/v1/embeddings` call to confirm OpenRouter returns a 2048-dim vector for `nvidia/nemotron-3-embed-1b:free` (and learn the `:free` daily cap). (Spike.)
3. **Test isolation mechanism** - transaction-rollback vs per-test schema for the Postgres fixture? Suggested: transaction-rollback for speed; switch to per-test schema if any test commits mid-run.
4. **Postgres fixture dependency** - a local Postgres only, or fall back to embedded-Postgres for CI without a DB? Suggested: require a local Postgres (env `TEST_DATABASE_URL`); document the embedded fallback.
5. **One-time MinIO upload** - is uploading `templates/*.md` + `output/*.md` into the `contracts` bucket part of this change or a manual ops step? Suggested: include a small `scripts/seed_minio.py` uploader as a task.
6. **DB name** - `database_url` currently points at `law_bentch` (likely a typo of `law_bench`). Confirm the intended name before provisioning.
