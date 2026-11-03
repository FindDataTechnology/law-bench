## 1. Project Setup & Dependencies

- [x] 1.1 Add FastAPI, uvicorn, pydantic to pyproject.toml dependencies
- [x] 1.2 Create `/fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/api/` directory structure
- [x] 1.3 Create `api/__init__.py` with version info
- [x] 1.4 Create `api/main.py` with FastAPI app instance and basic configuration
- [x] 1.5 Add startup script or entry point for running the API server

## 2. Pydantic Schemas

- [x] 2.1 Create `api/schemas.py` with request/response models for contract endpoints
- [x] 2.2 Define `ContractContentRequest` and `ContractContentResponse` schemas
- [x] 2.3 Define `ContractBatchRequest` and `ContractBatchResponse` schemas
- [x] 2.4 Define `ContractTypeCatalogResponse` and `TypeMetadataResponse` schemas
- [x] 2.5 Define `TagCombinationsResponse` and `TagValidateRequest/Response` schemas
- [x] 2.6 Define standardized `ErrorResponse` schema with trace_id

## 3. Dependency Injection

- [x] 3.1 Create `api/deps.py` with database session dependency
- [x] 3.2 Implement `get_db()` async generator for connection management
- [x] 3.3 Add settings/configuration dependency for environment variables
- [x] 3.4 Create `api/config.py` with Pydantic Settings class for API configuration

## 4. Core Route Handlers

- [x] 4.1 Create `api/routes/__init__.py` with router aggregation
- [x] 4.2 Create `api/routes/contracts.py` with contract-related endpoints
- [x] 4.3 Implement `POST /contracts/content` endpoint calling MCP tool
- [x] 4.4 Implement `POST /contracts/batch` endpoint with parallel generation
- [x] 4.5 Implement `GET /contracts/types` endpoint for catalog listing
- [x] 4.6 Implement `GET /contracts/types/{type}` endpoint for type metadata

## 5. Tag Route Handlers

- [x] 5.1 Create `api/routes/tags.py` with tag-related endpoints
- [x] 5.2 Implement `GET /tags/combinations/{type}` endpoint for enumeration
- [x] 5.3 Implement `POST /tags/validate` endpoint for tag validation
- [x] 5.4 Add query parameter support (filter_by_clause_coverage, refresh)

## 6. Health & Monitoring

- [x] 6.1 Implement `GET /health` endpoint returning `{"status": "healthy"}`
- [x] 6.2 Add database connectivity check to health endpoint
- [x] 6.3 Add structured logging middleware with request/response tracking
- [x] 6.4 Add trace_id propagation from request headers or auto-generation

## 7. Middleware

- [x] 7.1 Create `api/middleware.py` with CORS middleware configuration
- [x] 7.2 Implement API key authentication middleware (optional, env-controlled)
- [x] 7.3 Implement rate limiting middleware using slowapi or similar
- [x] 7.4 Add public endpoint bypass for /health, /docs, /redoc
- [x] 7.5 Configure CORS origins from environment variables

## 8. Error Handling

- [x] 8.1 Create global exception handler for NotFoundError (404)
- [x] 8.2 Create global exception handler for CoherenceError (422)
- [x] 8.3 Create global exception handler for authentication errors (401/403)
- [x] 8.4 Create global exception handler for rate limit errors (429)
- [x] 8.5 Ensure all errors return standardized ErrorResponse structure

## 9. Testing

- [x] 9.1 Create `tests/test_api/` directory for API tests
- [x] 9.2 Write unit tests for Pydantic schema validation
- [x] 9.3 Write integration tests for contract endpoints (mock DB)
- [x] 9.4 Write integration tests for batch endpoint with partial failures
- [x] 9.5 Write tests for authentication middleware (valid/invalid/missing keys)
- [x] 9.6 Write tests for rate limiting (exceed limit, reset after window)
- [x] 9.7 Write tests for CORS headers (preflight, allowed origins)
- [x] 9.8 Write tests for error handling (404, 422, 500 responses)

## 10. Documentation

- [x] 10.1 Add docstrings to all route handlers with examples
- [x] 10.2 Create `docs/api-server.md` with setup instructions
- [x] 10.3 Add curl examples for each endpoint
- [x] 10.4 Document environment variables (API_KEY_ENABLED, RATE_LIMIT_*, CORS_ORIGINS)
- [x] 10.5 Create Postman collection or OpenAPI schema export

## 11. Deployment

- [x] 11.1 Create Dockerfile for API server (optional)
- [x] 11.2 Create docker-compose.yml with API + dependencies (optional)
- [x] 11.3 Add systemd service file for production deployment (optional)
- [x] 11.4 Document deployment options in README

## 12. Integration & Verification

- [x] 12.1 Verify API server starts without errors
- [x] 12.2 Test all endpoints manually with curl/Postman
- [x] 12.3 Verify OpenAPI docs at /docs and /redoc
- [x] 12.4 Test authentication flow (enable/disable via env var)
- [x] 12.5 Test rate limiting behavior
- [x] 12.6 Verify backward compatibility (MCP tools still work)
- [x] 12.7 Update OpenSpec status after all implementations complete
