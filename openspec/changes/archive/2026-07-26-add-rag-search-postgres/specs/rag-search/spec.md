# rag-search Specification (delta)

## ADDED Requirements

### Requirement: Document Source in MinIO
The system SHALL read contract documents (seed templates and generated drafts) from an S3-compatible MinIO bucket configured via environment (`minio_host`, `minio_root_user`, `minio_root_password`). Documents SHALL be organized under a configured bucket with prefixes separating templates from drafts (e.g. `templates/` and `drafts/`). The system SHALL read documents lazily from MinIO rather than from the local filesystem, so the corpus is shared and durable across processes.

#### Scenario: List and read documents from the bucket
- **WHEN** the ingestion pipeline runs against a configured MinIO bucket containing `templates/service-agreement.md` and `drafts/employee-nda.md`
- **THEN** both documents are read from MinIO as markdown text
- **AND** no document is read from the local `templates/` or `output/` directories

#### Scenario: Bucket and prefix are configurable
- **WHEN** the bucket name or the templates/drafts prefixes are changed via environment
- **THEN** ingestion reads from the newly configured locations without code changes

### Requirement: Embedding via OpenRouter
The system SHALL embed document chunks and queries using the `nvidia/nemotron-3-embed-1b:free` model served through OpenRouter's OpenAI-compatible `/api/v1/embeddings` endpoint, configured via `OPENROUTER_API_BASE` (default `https://openrouter.ai/api/v1`) and `OPENROUTER_API_KEY`. The output embedding dimension SHALL be 2048. Ingestion (document) embeddings and query embeddings SHALL use the same model and dimensions.

#### Scenario: A chunk is embedded to a 2048-dimensional vector
- **WHEN** a document chunk is embedded via the OpenRouter embedding client
- **THEN** the returned vector has exactly 2048 float dimensions
- **AND** the request is sent to `OPENROUTER_API_BASE`/embeddings with model `nvidia/nemotron-3-embed-1b:free`

#### Scenario: Query and document embeddings share the model
- **WHEN** a search query is embedded at query time
- **THEN** it uses the same model and 2048 dimensions used at ingestion time
- **AND** cosine similarity between query and document vectors is meaningful

#### Scenario: Free-tier limits and unavailability are handled
- **WHEN** the OpenRouter `:free` model returns a rate-limit or availability error during ingestion
- **THEN** the client retries with backoff and, on persistent failure, records the failed chunk without aborting the whole ingestion batch
- **AND** a clear error is surfaced for manual retry

### Requirement: Elasticsearch Vector Store
The system SHALL store document chunk embeddings in an Elasticsearch index configured via `elastic_search_host`, `elastic_search_user`, and `elastic_search_pass`. The index mapping SHALL declare a `dense_vector` field with `dims: 2048` and `similarity: cosine` (the model output is L2-normalized, so cosine and dot-product agree). Each indexed document SHALL carry the chunk text and metadata (source document path, contract type where derivable, and section/heading where available). The system SHALL detect a dimension mismatch between the configured model and an existing index and refuse to silently corrupt the index.

#### Scenario: The index is created with the correct mapping
- **WHEN** the vector store is initialized against an Elasticsearch cluster with no prior index
- **THEN** an index is created with a `dense_vector` field of `dims: 2048` and `similarity: cosine`
- **AND** stored documents carry their chunk text and source metadata

#### Scenario: Dimension mismatch is rejected
- **WHEN** the configured embedding model implies 2048 dims but an existing index was created with a different dimension
- **THEN** the system raises a clear configuration error rather than writing mismatched vectors
- **AND** no partial vectors are written

#### Scenario: A model swap requires reindexing
- **WHEN** the embedding model is changed after documents have been indexed
- **THEN** the system requires an explicit reindex (drop and re-ingest) before search
- **AND** search is not served against stale vectors of the wrong dimension

### Requirement: Document Ingestion Pipeline
The system SHALL provide a re-runnable pipeline that reads documents from MinIO, splits each into chunks, embeds the chunks via OpenRouter, and upserts them into the Elasticsearch vector store. The pipeline SHALL be idempotent: re-running it over unchanged documents SHALL NOT create duplicate chunks. The pipeline SHALL be invokable from a CLI entry point and SHALL report progress and any per-chunk failures.

#### Scenario: Run ingestion over the corpus
- **WHEN** the ingestion pipeline is run against a populated MinIO bucket
- **THEN** every document is chunked, embedded, and stored in Elasticsearch with source metadata
- **AND** the run reports the number of documents and chunks ingested

#### Scenario: Re-running ingestion is idempotent
- **WHEN** the ingestion pipeline is run a second time over unchanged documents
- **THEN** no duplicate chunks are created
- **AND** changed documents are updated and deleted documents are removed from the index

#### Scenario: A single bad document does not abort the batch
- **WHEN** one document fails to parse or embed during ingestion
- **THEN** the pipeline records the failure and continues with the remaining documents
- **AND** the run exits non-zero only if no document was ingested successfully

### Requirement: Semantic Search API
The system SHALL expose a JSON endpoint `GET /api/search?q=<query>` (and an equivalent `POST` accepting a query body) that returns ranked chunks for a natural-language query using the LlamaIndex query engine over the Elasticsearch vector store. Each result SHALL include the chunk text, its source document path, and a relevance score. The endpoint SHALL return an empty result list (not an error) when no chunks match.

#### Scenario: Search returns ranked chunks for a Chinese query
- **WHEN** a client requests `GET /api/search?q=保密义务` against an indexed corpus
- **THEN** the response is a JSON list of chunks ranked by cosine similarity
- **AND** each result carries its chunk text, source document path, and score

#### Scenario: No matches returns an empty list
- **WHEN** a client searches for a query with no similar chunks in the index
- **THEN** the response is `[]` with HTTP 200
- **AND** no error is raised

#### Scenario: Search works across locales
- **WHEN** a search query is submitted in Chinese or English
- **THEN** ranked results are returned using the shared embedding space
- **AND** the endpoint does not depend on the UI locale

### Requirement: Search Page
The system SHALL provide an HTML page at `/search` with a query input and a ranked results list, consistent with the existing localized UI chrome (nav, locale switch). Results SHALL link back to their source document where viewable.

#### Scenario: A user searches from the page
- **WHEN** a user submits a query on `/search`
- **THEN** ranked chunks are rendered with their source path and a relevance score
- **AND** the page chrome is localized per the active locale

### Requirement: CrewAI RAG Retrieval Tool
The system SHALL expose semantic retrieval as a CrewAI tool that the drafter agent can call to ground contract generation in retrieved precedent chunks. The tool SHALL be optional and configurable (on/off via environment). When the retrieval backend (MinIO, Elasticsearch, or OpenRouter) is unavailable, the tool SHALL degrade gracefully - returning no context and letting the drafter proceed without retrieval - rather than failing the drafting run.

#### Scenario: The drafter retrieves context before drafting
- **WHEN** the RAG tool is enabled and the drafter agent is invoked
- **THEN** the drafter can call the retrieval tool with the drafting request
- **AND** retrieved chunks are made available as context for generation

#### Scenario: Retrieval is optional
- **WHEN** the RAG tool is disabled via configuration
- **THEN** the drafter proceeds without any retrieval calls
- **AND** drafting behaves as before this change

#### Scenario: Backend unavailability degrades gracefully
- **WHEN** Elasticsearch or OpenRouter is unreachable during a drafting run with the tool enabled
- **THEN** the tool returns no context and the drafter still completes the draft
- **AND** no unhandled exception propagates to the crew
