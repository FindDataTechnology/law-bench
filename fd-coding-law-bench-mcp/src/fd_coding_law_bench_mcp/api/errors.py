"""Centralized error handling for the HTTP API."""

import traceback
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from .schemas import ErrorResponse


def create_error_response(
    error: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
    status_code: int = 500,
) -> JSONResponse:
    """Create a standardized error response.

    Args:
        error: Error type/name (e.g., "ValidationError", "NotFound")
        message: Human-readable error message
        details: Additional error details (optional)
        trace_id: Trace ID for debugging (optional)
        status_code: HTTP status code (default: 500)

    Returns:
        JSONResponse with standardized error structure
    """
    error_data = ErrorResponse(
        error=error,
        message=message,
        details=details,
        trace_id=trace_id,
    )
    return JSONResponse(
        status_code=status_code,
        content=error_data.model_dump(exclude_none=True),
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle HTTPException and convert to standardized error response.

    This handler ensures all HTTP exceptions return the same error format.
    """
    # Extract trace_id from request headers if available
    trace_id = request.headers.get("X-Trace-ID")

    # Build details from exception
    details = None
    if isinstance(exc.detail, dict):
        details = exc.detail
    else:
        details = {"detail": exc.detail}

    return create_error_response(
        error=f"HTTP{exc.status_code}",
        message=str(exc.detail) if not isinstance(exc.detail, dict) else exc.detail.get("message", str(exc.detail)),
        details=details,
        trace_id=trace_id,
        status_code=exc.status_code,
    )


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle validation errors (e.g., Pydantic validation).

    Converts validation errors to standardized 422 response.
    """
    from fastapi.exceptions import RequestValidationError

    trace_id = request.headers.get("X-Trace-ID")

    if isinstance(exc, RequestValidationError):
        # Extract validation errors
        errors = []
        for error in exc.errors():
            errors.append({
                "field": ".".join(str(loc) for loc in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            })

        return create_error_response(
            error="ValidationError",
            message="Request validation failed",
            details={"validation_errors": errors},
            trace_id=trace_id,
            status_code=422,
        )

    # Fallback for other validation errors
    return create_error_response(
        error="ValidationError",
        message=str(exc),
        trace_id=trace_id,
        status_code=422,
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions.

    Converts all unhandled exceptions to standardized 500 response.
    In production, detailed error info is hidden for security.
    """
    trace_id = request.headers.get("X-Trace-ID")

    # Log the full exception for debugging
    print(f"Unhandled exception: {type(exc).__name__}: {exc}")
    print(traceback.format_exc())

    # In production, hide detailed error info
    # In development, include exception details
    from .config import get_settings
    settings = get_settings()

    if settings.debug:
        details = {
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "traceback": traceback.format_exc(),
        }
    else:
        details = {
            "exception_type": type(exc).__name__,
        }

    return create_error_response(
        error="InternalServerError",
        message="An unexpected error occurred",
        details=details,
        trace_id=trace_id,
        status_code=500,
    )


async def not_found_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle NotFoundError exceptions.

    Converts NotFoundError to standardized 404 response.
    """
    trace_id = request.headers.get("X-Trace-ID")

    return create_error_response(
        error="NotFound",
        message=str(exc),
        trace_id=trace_id,
        status_code=404,
    )


async def coherence_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle CoherenceError exceptions.

    Converts CoherenceError to standardized 422 response.
    """
    trace_id = request.headers.get("X-Trace-ID")

    return create_error_response(
        error="CoherenceError",
        message=str(exc),
        trace_id=trace_id,
        status_code=422,
    )


def register_exception_handlers(app) -> None:
    """Register all exception handlers with the FastAPI app.

    This should be called during app initialization.
    """
    from fastapi.exceptions import RequestValidationError

    from src.clauses.coherence import CoherenceError
    from src.eval.errors import NotFoundError

    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(NotFoundError, not_found_exception_handler)
    app.add_exception_handler(CoherenceError, coherence_error_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
