"""Manage-layer errors, mapped to HTTP responses by the API layer.

Lives in its own module so the CRUD modules, the run-store, and the web layer
can all import a single error hierarchy without pulling in CRUD code.
"""

from __future__ import annotations


class ManageError(Exception):
    """Base for manage-layer errors."""


class NotFoundError(ManageError):
    """A rubric or criterion was not found (-> HTTP 404)."""


class HarborReadOnlyError(ManageError, ValueError):
    """An operation was attempted on a read-only harbor rubric (-> HTTP 403)."""


class ConflictError(ManageError, ValueError):
    """A uniqueness constraint would be violated (-> HTTP 409)."""


class ValidationError(ManageError, ValueError):
    """Input failed validation (-> HTTP 400)."""
