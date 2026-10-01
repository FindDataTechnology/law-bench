# Law Bench Contract Generation API

A FastAPI-based async REST API for generating legal contracts via tag-driven
assembly. This site is the shareable documentation for the HTTP API.

## What's here

- **[API Reference](api-reference.md)** — Every endpoint with request/response
  schemas, curl examples, and error codes. The canonical reference.
- **[Tag Vocabulary](tag-vocabulary.md)** — Valid tag values, type-specific
  dimensions, scenario vocabularies, and the full 43-contract-type catalog.
- **[Server Setup](api-server.md)** — How to run, configure, and deploy the API
  server (CORS, auth, rate limiting, env vars).

## Quick start

```bash
# Start the server
uvicorn fd_coding_law_bench_mcp.api.main:app --port 8000

# Generate a sale contract (markdown, no file I/O)
curl -X POST http://localhost:8000/contracts/content \
  -H "Content-Type: application/json" \
  -d '{"contract_type": "sale", "format": "markdown"}'
```

## Interactive docs

When the server is running, Swagger UI and ReDoc are auto-generated:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

This static site is the readable reference; the live Swagger is for interactive
exploration once you have a server running.

## Key concepts

- **Tag-driven assembly**: Contracts are assembled from clauses by precedence
  `custom > tagged > base`, filtered by `stance` and `scenario`.
- **43 contract types**: `sale`, `lease`, `employment`, `loan`, and 39 more
  (see [Tag Vocabulary](tag-vocabulary.md#contract-type-catalog)).
- **Content-first API**: `format="markdown"` returns contract text instantly
  without generating DOCX/PDF files.
- **Batch generation**: Generate many contracts in parallel across tag
  combinations.
