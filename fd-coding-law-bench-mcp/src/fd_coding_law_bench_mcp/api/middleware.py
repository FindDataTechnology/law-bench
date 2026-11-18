"""API middleware for authentication and rate limiting."""

from typing import List

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from .config import get_settings


# ============================================================================
# API Key Authentication (HTTP middleware)
# ============================================================================

async def auth_middleware(request: Request, call_next):
    """HTTP middleware enforcing optional API key authentication.

    Reads the current settings on every request so toggling
    ``API_KEY_ENABLED`` takes effect without a restart (useful for tests).
    Public endpoints (``/health``, ``/docs``, ``/redoc``, ``/openapi.json``)
    always bypass authentication. When auth is disabled (the default), all
    requests pass through unchanged.
    """
    settings = get_settings()

    # Skip auth when disabled or for public endpoints
    if not settings.api_key_enabled or request.url.path in settings.public_endpoints:
        return await call_next(request)

    api_key = request.headers.get("X-API-Key")
    if not api_key:
        return JSONResponse(
            status_code=401,
            content={
                "error": "Unauthorized",
                "message": "API key required. Provide X-API-Key header.",
            },
        )

    if not settings.api_keys or api_key not in settings.api_keys:
        return JSONResponse(
            status_code=403,
            content={
                "error": "Forbidden",
                "message": "Invalid API key.",
            },
        )

    return await call_next(request)


async def verify_api_key(request: Request) -> None:
    """Verify API key from request header (dependency form).

    Raises HTTPException if authentication is enabled but no valid key provided.

    Checks X-API-Key header against configured API keys.
    """
    settings = get_settings()

    # Skip authentication if disabled
    if not settings.api_key_enabled:
        return

    # Skip authentication for public endpoints
    if request.url.path in settings.public_endpoints:
        return

    # Get API key from header
    api_key = request.headers.get("X-API-Key")

    if not api_key:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "Unauthorized",
                "message": "API key required. Provide X-API-Key header.",
            },
        )

    # Check if API key is valid
    if not settings.api_keys or api_key not in settings.api_keys:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "Forbidden",
                "message": "Invalid API key.",
            },
        )


# ============================================================================
# Rate Limiting
# ============================================================================

def create_rate_limiter() -> Limiter:
    """Create rate limiter based on configuration.

    Returns a Limiter instance configured with the appropriate backend
    (memory or Redis) and default rate limits.
    """
    settings = get_settings()

    if not settings.rate_limit_enabled:
        # Return a disabled limiter
        return Limiter(
            key_func=get_remote_address,
            default_limits=[],
            storage_uri="memory://",
        )

    # Configure storage backend
    if settings.rate_limit_backend == "redis" and settings.redis_url:
        storage_uri = settings.redis_url
    else:
        storage_uri = "memory://"

    # Create limiter with default rate limit
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=[f"{settings.rate_limit_requests}/{settings.rate_limit_window}"],
        storage_uri=storage_uri,
    )

    return limiter


def get_rate_limit_decorator(endpoint_type: str = "default"):
    """Get rate limit decorator for specific endpoint type.

    Args:
        endpoint_type: Type of endpoint ("default", "batch", "catalog")
                      Each type can have different rate limits.

    Returns:
        Decorator function for rate limiting
    """
    settings = get_settings()

    if not settings.rate_limit_enabled:
        # Return no-op decorator
        def noop_decorator(func):
            return func
        return noop_decorator

    limiter = create_rate_limiter()

    # Define rate limits per endpoint type
    rate_limits = {
        "default": f"{settings.rate_limit_requests}/{settings.rate_limit_window}",
        "batch": "10/minute",  # Stricter limit for batch operations
        "catalog": "60/minute",  # More permissive for read-only catalog
    }

    limit = rate_limits.get(endpoint_type, rate_limits["default"])

    return limiter.limit(limit)
