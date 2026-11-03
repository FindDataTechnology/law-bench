## Context

**Current State:**
- Async contract generation tools exist as MCP tools (Model Context Protocol)
- Tools use `anyio.to_thread.run_sync` for DB-bound operations
- PostgreSQL connection via psycopg (sync driver)
- No HTTP API surface - only accessible via MCP clients

**Constraints:**
- Must reuse existing business logic from `src.clauses.assemble`, `src.clauses.tags`, etc.
- Must maintain backward compatibility with MCP tools
- Database connection pool is sync (psycopg) - async driver upgrade deferred
- Docx/pdf rendering remains sync (no async equivalent)

---

## Goals / Non-Goals

**Goals:**
1. Provide HTTP REST API for all async contract generation capabilities
2. Enable web frontend, mobile app, and external system integration
3. Auto-generate OpenAPI documentation for developer experience
4. Support optional authentication and rate limiting for production deployment
5. Reuse existing MCP tool implementations (no code duplication)

**Non-Goals:**
1. Replace MCP tools (both coexist)
2. Async database driver (psycopg → asyncpg migration deferred)
3. WebSocket or streaming responses (batch returns complete lists)
4. File upload/download endpoints (content-first, no forced file I/O)

---

## Decisions

### Decision 1: FastAPI over Flask/Django

**Choice:** Use FastAPI as the HTTP framework.

**Rationale:**
- Native async support (async def route handlers)
- Automatic OpenAPI schema generation from Pydantic models
- Built-in request validation via Pydantic
- High performance (Starlette + Uvicorn)
- Modern Python (type hints, async/await)

**Alternatives Considered:**
- **Flask:** No native async, requires extensions for OpenAPI → Rejected
- **Django REST Framework:** Heavyweight, ORM mismatch (we use raw SQL) → Rejected
- **aiohttp:** Lower-level, no auto OpenAPI → Rejected

### Decision 2: Reuse MCP tool implementations

**Choice:** HTTP routes call existing MCP tool functions directly, not duplicate logic.

**Implementation:**
```python
# api/routes/contracts.py
from ..tools.content import contract_content as _mcp_contract_content

@router.post("/content")
async def contract_content(request: ContractContentRequest):
    result = await _mcp_contract_content(
        contract_type=request.contract_type,
        tags=request.tags,
        format=request.format,
    )
    return result
```

**Rationale:**
- Single source of truth for business logic
- MCP tools already handle errors, validation, caching
- Reduces maintenance burden (no parallel implementations)
- MCP tools remain functional (backward compat)

**Trade-off:** MCP tool signatures may not perfectly match REST conventions → Adapt at route layer with Pydantic models.

### Decision 3: Pydantic models for request/response validation

**Choice:** Define Pydantic models for all request/response schemas.

**Implementation:**
```python
# api/schemas.py
from pydantic import BaseModel, Field
from typing import Literal

class ContractContentRequest(BaseModel):
    contract_type: str = Field(..., description="Contract class key")
    tags: dict | None = Field(None, description="Tag dict with scenario/stance")
    format: Literal["markdown", "docx", "pdf", "both"] = Field("markdown")

class ContractContentResponse(BaseModel):
    trace_id: str
    contract_type: str
    body_text: str
    slots: list[str]
    instructions: list[dict]
    law_refs: list[dict]
```

**Rationale:**
- Automatic validation (422 on bad input)
- OpenAPI schema generation (Swagger UI)
- Type safety (IDE autocomplete, mypy)
- Consistent with FastAPI idioms

### Decision 4: Dependency injection for DB sessions

**Choice:** Use FastAPI's `Depends()` for database session management.

**Implementation:**
```python
# api/deps.py
from src.eval.db import connect

async def get_db():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()

# api/routes/contracts.py
@router.post("/content")
async def contract_content(
    request: ContractContentRequest,
    db: Any = Depends(get_db)
):
    result = await _mcp_contract_content(..., db=db)
    return result
```

**Rationale:**
- Connection pooling (reuse across requests)
- Automatic cleanup (finally block)
- Testable (inject mock DB in tests)
- Follows FastAPI best practices

### Decision 5: Optional authentication via middleware

**Choice:** API key authentication as optional middleware, disabled by default.

**Implementation:**
```python
# api/middleware.py
from fastapi import Request, HTTPException

async def api_key_auth(request: Request):
    if not settings.API_KEY_ENABLED:
        return  # Skip auth
    
    api_key = request.headers.get("X-API-Key")
    if not api_key or api_key not in settings.API_KEYS:
        raise HTTPException(status_code=401, detail="API key required")

# api/main.py
app.middleware("http")(api_key_auth)
```

**Rationale:**
- Development-friendly (no auth by default)
- Production-ready (enable via env var)
- Simple implementation (no JWT/OAuth complexity)
- Public endpoints bypass auth (health, docs)

### Decision 6: In-memory rate limiting with Redis option

**Choice:** In-memory rate limiting by default, optional Redis backend for multi-worker.

**Implementation:**
```python
# api/middleware.py
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@router.post("/batch")
@limiter.limit("10/minute")  # Stricter for expensive ops
async def contract_generate_batch(request: Request, ...):
    ...
```

**Rationale:**
- Simple deployment (no Redis required)
- Fast (in-memory counters)
- Optional Redis for horizontal scaling
- Per-endpoint limits (batch vs content)

**Trade-off:** In-memory doesn't share across workers → Use Redis if running multiple Uvicorn workers.

### Decision 7: CORS configuration via environment

**Choice:** CORS middleware with configurable allowed origins.

**Implementation:**
```python
# api/main.py
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,  # ["http://localhost:3000"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Rationale:**
- Web frontend integration (React/Vue apps)
- Configurable per environment (dev vs prod)
- Secure defaults (explicit origin list, not `*`)

---

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|------|--------|------------|
| Sync DB driver blocks event loop | Medium | Acceptable for MVP; asyncpg upgrade planned for v2 |
| Rate limiting not shared across workers | Low | Use Redis backend if running multiple workers |
| API key auth is simple (no rotation/revocation) | Low | Sufficient for internal use; add JWT/OAuth if needed |
| MCP tool signatures may not match REST conventions | Low | Adapt at route layer with Pydantic models |
| Docx/pdf rendering still sync | Low | File output always opt-in; content-first is default |

---

## Migration Plan

**Phase 1: Add HTTP API alongside MCP**
- No breaking changes; both coexist
- Deploy API server as separate service
- Test endpoints in staging environment

**Phase 2: Update documentation**
- Document HTTP API endpoints with examples
- Provide Postman collection or curl examples
- Migration guide for MCP-only users

**Phase 3: Optional features**
- Enable authentication for production
- Configure rate limiting based on load
- Add Redis backend if scaling horizontally

---

## Open Questions

1. **What's the default port?** 8000 seems standard for FastAPI; configurable via env var.
2. **Should we support API versioning?** `/api/v1/...` prefix for future breaking changes? Likely unnecessary for internal use.
3. **Do we need request logging?** Yes, add structured logging with trace IDs for debugging.
4. **Should batch endpoint be synchronous or return job ID?** Synchronous for MVP; async job queue if batch operations take >30s.
