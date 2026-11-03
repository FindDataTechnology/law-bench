## Why

The async contract generation tools implemented in the previous change are currently only accessible via MCP (Model Context Protocol), which limits their use to AI assistants and MCP-compatible clients. There's no standalone HTTP API server that external applications, web frontends, or mobile apps can consume directly. This change creates a FastAPI-based async HTTP server that exposes all the new contract generation capabilities as REST endpoints, enabling broader integration and real-time API consumption.

## What Changes

- **New HTTP API Server**: FastAPI application with async endpoints for all contract generation tools
- **REST Endpoints**: 
  - `POST /contracts/content` - Get contract content (markdown/JSON)
  - `POST /contracts/batch` - Batch generate multiple contracts
  - `GET /contracts/types` - List all contract types with metadata
  - `GET /contracts/types/{type}` - Get detailed type metadata
  - `GET /tags/combinations/{type}` - Enumerate valid tag combinations
  - `POST /tags/validate` - Validate tag dict
- **Async Request Handling**: True async HTTP handlers with connection pooling
- **OpenAPI Documentation**: Auto-generated Swagger UI and OpenAPI schema
- **CORS Support**: Cross-origin requests for web frontend integration
- **Health Checks**: `/health` endpoint for monitoring and load balancers

## Capabilities

### New Capabilities

- `http-api-server`: FastAPI-based HTTP server with async REST endpoints for contract generation
- `api-authentication`: Optional API key authentication for securing endpoints
- `api-rate-limiting`: Request throttling to prevent abuse and manage load

### Modified Capabilities

None. This is purely additive - the existing MCP tools remain functional.

## Impact

**Affected Code**:
- New `/fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/api/` directory with FastAPI app
- New `/fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/api/main.py` - FastAPI application entry point
- New `/fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/api/routes/` - Route handlers
- New `/fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/api/schemas.py` - Pydantic request/response models
- New `/fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/api/deps.py` - Dependency injection (DB sessions, auth)
- New `/fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/api/middleware.py` - CORS, rate limiting middleware

**Dependencies**:
- Add `fastapi` for HTTP framework
- Add `uvicorn` for ASGI server
- Add `pydantic` (already present via FastAPI) for request/response validation
- Add `python-jose` or similar for JWT/API key auth (optional)

**API Surface**:
- HTTP REST API on configurable port (default 8000)
- OpenAPI docs at `/docs` (Swagger UI) and `/redoc` (ReDoc)
- JSON response format with standardized error structure
- Request validation via Pydantic models

**Systems**:
- Runs as standalone service or alongside MCP server
- Shares database connection pool with MCP tools
- Can be deployed independently (Docker, systemd, etc.)
