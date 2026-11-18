"""Shared error response structures for batch tools.

Standardizes error format across all async tools: ``{success, error: {type, message, details}}``.
Includes trace_id generation for debugging and per-item failure reporting.
"""

from __future__ import annotations

import uuid
from typing import Any


def make_error_response(
    trace_id: str | None = None,
    error_type: str = "UnknownError",
    message: str = "An error occurred",
    details: dict | None = None,
) -> dict:
    """Create standardized error response structure.

    Parameters:
        trace_id: optional tracing ID for debugging. Auto-generated if None.
        error_type: exception class name or error category.
        message: human-readable error description.
        details: optional additional context (tags used, stack trace, etc.).

    Returns:
        ``{success: False, trace_id, error: {type, message, details}}``
    """
    return {
        "success": False,
        "trace_id": trace_id or str(uuid.uuid4()),
        "error": {
            "type": error_type,
            "message": message,
            "details": details or {},
        },
    }


def make_success_response(
    trace_id: str | None = None,
    **kwargs: Any,
) -> dict:
    """Create standardized success response structure.

    Parameters:
        trace_id: optional tracing ID. Auto-generated if None.
        **kwargs: additional response fields (body_text, slots, etc.).

    Returns:
        ``{success: True, trace_id, ...kwargs}``
    """
    return {
        "success": True,
        "trace_id": trace_id or str(uuid.uuid4()),
        **kwargs,
    }


def extract_error_info(exc: Exception) -> dict:
    """Extract structured error info from an exception.

    Returns ``{type, message, details}`` suitable for error responses.
    """
    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "details": {
            "module": exc.__class__.__module__,
        },
    }
