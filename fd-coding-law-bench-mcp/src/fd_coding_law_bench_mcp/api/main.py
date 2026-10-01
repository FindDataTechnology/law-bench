"""FastAPI application entry point for HTTP contract generation API."""

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .config import APISettings, get_settings
from .deps import get_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown events."""
    # Startup: log configuration
    settings = get_settings()
    print(f"Starting law-bench HTTP API server on {settings.host}:{settings.port}")
    print(f"CORS origins: {settings.cors_origins}")
    print(f"API auth enabled: {settings.api_key_enabled}")
    print(f"Rate limiting enabled: {settings.rate_limit_enabled}")
    yield
    # Shutdown: cleanup
    print("Shutting down law-bench HTTP API server")


# Initialize FastAPI app
settings = get_settings()

app = FastAPI(
    title="Law Bench Contract Generation API",
    description="Async REST API for generating legal contracts via tag-driven assembly",
    version="0.1.0",
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Add rate limiter if enabled
if settings.rate_limit_enabled:
    from slowapi import Limiter, _rate_limit_exceeded_handler

    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=[f"{settings.rate_limit_requests}/{settings.rate_limit_window} seconds"],
        storage_uri=settings.redis_url or "memory://",
    )
    app.state.limiter = limiter

    @app.exception_handler(RateLimitExceeded)
    async def custom_rate_limit_handler(request: Request, exc: RateLimitExceeded):
        return await _rate_limit_exceeded_handler(request, exc)


# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add API key authentication middleware (no-op when API_KEY_ENABLED=false).
# Reads X-API-Key header against the configured key set; public endpoints
# (/health, /docs, /redoc, /openapi.json) always bypass auth.
from .middleware import auth_middleware  # noqa: E402

app.middleware("http")(auth_middleware)

# Import and include routers (import after CORS middleware registration)
from .routes import contracts, tags  # noqa: E402

app.include_router(contracts.router, prefix="/contracts", tags=["contracts"])
app.include_router(tags.router, prefix="/tags", tags=["tags"])

# Agent runs endpoints for contract-review-agent metrics
from .routes import agent_runs  # noqa: E402

app.include_router(agent_runs.router, prefix="/api", tags=["Agent Runs"])

# Health check endpoint
@app.get("/health", include_in_schema=False)
async def health_check():
    """Health check endpoint for load balancers and monitoring."""
    return {"status": "healthy"}


# Register exception handlers
from .errors import register_exception_handlers  # noqa: E402

register_exception_handlers(app)
