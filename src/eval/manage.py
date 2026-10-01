"""Backward-compatible facade re-exporting the split CRUD modules.

The CRUD logic now lives in focused modules:

- ``rubric_crud`` : rubrics + criteria (read/write, harbor read-only guards)
- ``prompt_crud`` : generation prompts (always editable, no harbor analog)
- ``errors``      : the ``ManageError`` hierarchy (mapped to HTTP by the web layer)
- ``db``          : shared SQLite helpers (connection, timestamps, predicates)

This module re-exports the public surface those modules expose so existing
``from src.eval import manage as M`` and ``from src.eval.manage import
ConflictError`` imports keep working unchanged. New code may import directly
from the split modules.
"""

from __future__ import annotations

from .errors import (
    ConflictError,
    HarborReadOnlyError,
    ManageError,
    NotFoundError,
    ValidationError,
)
from .prompt_crud import (
    create_prompt,
    delete_prompt,
    get_prompt,
    get_prompt_by_id,
    list_prompts,
    update_prompt,
)
from .rubric_crud import (
    add_criterion,
    create_rubric,
    delete_criterion,
    delete_rubric,
    get_rubric_by_id,
    get_rubric_detail,
    list_rubrics_with_counts,
    reorder_criteria,
    update_criterion,
    update_rubric,
)

__all__ = [
    "ManageError",
    "NotFoundError",
    "HarborReadOnlyError",
    "ConflictError",
    "ValidationError",
    "list_rubrics_with_counts",
    "get_rubric_detail",
    "get_rubric_by_id",
    "create_rubric",
    "update_rubric",
    "delete_rubric",
    "add_criterion",
    "update_criterion",
    "delete_criterion",
    "reorder_criteria",
    "list_prompts",
    "get_prompt",
    "get_prompt_by_id",
    "create_prompt",
    "update_prompt",
    "delete_prompt",
]
