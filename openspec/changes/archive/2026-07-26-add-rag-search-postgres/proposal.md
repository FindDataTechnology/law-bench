## Why

The contract drafter has no retrieval: it drafts from fixed seed templates only, with no way to search prior drafts or template clauses by meaning. Its whole relational data layer is locked to a single local SQLite file (`db/evaluation_rules.db`) - a constraint the existing specs mandate at both the storage and test level - which blocks durable, multi-process, or containerized deployment against a shared store. This change adds LlamaIndex-based semantic search over contract documents stored in MinIO and embedded (via OpenRouter's free embedding model) into Elasticsearch, exposed both as a web search API/page and as a CrewAI RAG tool the drafter can call; and it migrates the relational data layer from SQLite to PostgreSQL.

## What Changes

- **New RAG search subsystem**: ingest contract templates + generated drafts from MinIO, chunk + embed via OpenRouter `nvidia/nemotron-3-embed-1b:free` (2048-dim, L2-normalized), store vectors in Elasticsearch, and serve semantic search through a LlamaIndex query engine.
- **New `/api/search` JSON endpoint + `/search` page**: return ranked chunks (text, source doc, path, score) for a natural-language (Chinese) query.
- **New CrewAI RAG retrieval tool**: the drafter agent can retrieve relevant precedent chunks to ground generation in retrieved material.
- **BREAKING (storage)**: migrate the evaluation data layer from SQLite (`db/evaluation_rules.db`) to PostgreSQL (DSN from `database_url`). The `get_db()` seam changes from returning a `Path` to returning a Postgres connection/session. SQL dialect migrated: `?`->`%s`, `INTEGER PRIMARY KEY AUTOINCREMENT`->`BIGINT GENERATED ALWAYS AS IDENTITY`, `PRAGMA table_info`/`sqlite_master`->`information_schema`, `cur.lastrowid`->`RETURNING id`, `PRAGMA foreign_keys` removed (on by default in Postgres).
- **BREAKING (tests)**: the hermetic test DB posture changes from a per-test throwaway SQLite file to a per-test Postgres fixture; the test suite now requires a local Postgres. The no-external-network / no-LLM-call guarantee is preserved (Postgres is local; embedding/ES/MinIO are faked in tests).

## Capabilities

### New Capabilities
- `rag-search`: Semantic search over contract documents - MinIO document ingestion, OpenRouter embedding (`nvidia/nemotron-3-embed-1b:free`, 2048-dim), an Elasticsearch vector store, a LlamaIndex query engine, a `/api/search` JSON endpoint + `/search` page, and a CrewAI RAG retrieval tool for the drafter.

### Modified Capabilities
- `evaluation-rules`: the storage requirement changes from SQLite at `db/evaluation_rules.db` to PostgreSQL (DSN from `database_url`); the `PRAGMA table_info` additive-column migration moves to an `information_schema`-based guard; the `get_db` seam returns a Postgres connection, not a `Path`. Adds a new requirement for Postgres connection + idempotent schema management.
- `generation-prompts`: prompt storage moves from `db/evaluation_rules.db` (SQLite) to PostgreSQL; the `prompts` table is created by the same schema source of truth as `rubrics`/`criteria`, now over Postgres.
- `test-suite`: the hermetic test DB posture changes from a per-test throwaway SQLite file to a per-test Postgres fixture; the `get_db` dependency override now points at a throwaway Postgres, not a temp file path. The no-external-network / no-LLM-call guarantee is retained.

## Impact

- **Code**:
  - New `src/search/` package: MinIO reader, OpenRouter embedding client (`OpenAILikeEmbedding`), Elasticsearch vector store wiring, ingestion pipeline, LlamaIndex query engine, CrewAI retrieval tool. New `/api/search` route and `/search` page + template.
  - Modified: `src/eval/db.py`, `src/eval/store.py`, `src/eval/prompt_crud.py`, `src/eval/rubric_crud.py`, `src/eval/harbor_seed.py` (`sqlite3` -> `psycopg`); `src/web/deps.py` (`get_db` seam); `src/settings.py` (DB DSN + search-service config); `src/crew.py` + `src/config/agents.yaml` / `src/config/tasks.yaml` (RAG tool wiring).
- **Data / DB**: one-time migration of existing SQLite data (rubrics, criteria, prompts, eval_runs, eval_criteria_results, compare_runs) into Postgres. Table/column/constraint shape preserved; dialect translated. The Elasticsearch index is new (2048-dim `dense_vector`).
- **Dependencies**: add `llama-index-core`, `llama-index-vector-stores-elasticsearch`, `llama-index-embeddings-openai-like`, `llama-index-readers-minio`, `psycopg[binary]`, `elasticsearch`, `boto3`; plus a test-time Postgres fixture dependency (decision in design.md).
- **APIs**: new `/api/search`. Existing `/api/*` contracts unchanged in shape (the storage swap is transparent to callers).
- **Tests**: test suite reworked onto a Postgres fixture (the largest cost of the storage swap); new tests for the search pipeline (ingestion, 2048-dim embedding, search ranking, RAG tool) with MinIO/ES/OpenRouter faked for hermeticity.
- **Risk**: high and cross-cutting. The Postgres swap touches all tested data code and breaks the current SQLite-file test seam. The RAG piece is additive (lower risk) but depends on three external services (MinIO, ES, OpenRouter) whose reachability, auth, and ES version/KNN must be verified before implementation. The embedding model dims (2048) lock the ES index; swapping the model later requires a full reindex.
