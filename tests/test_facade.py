"""Backward-compat test: ``src.eval.manage`` re-exports the split CRUD modules.

After splitting ``manage.py`` into ``rubric_crud`` / ``prompt_crud`` / ``errors``
/ ``db``, the ``manage`` facade MUST keep exposing the same public names so
existing ``from src.eval import manage as M`` imports keep working.
"""

from __future__ import annotations

import src.eval.manage as M
from src.eval import errors, prompt_crud, rubric_crud


def test_facade_exposes_rubric_and_criterion_crud():
    for name in (
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
    ):
        assert callable(getattr(M, name)), f"manage.{name} should be callable"


def test_facade_exposes_prompt_crud():
    for name in (
        "list_prompts",
        "get_prompt",
        "get_prompt_by_id",
        "create_prompt",
        "update_prompt",
        "delete_prompt",
    ):
        assert callable(getattr(M, name)), f"manage.{name} should be callable"


def test_facade_exposes_error_hierarchy():
    for name in (
        "ManageError",
        "NotFoundError",
        "HarborReadOnlyError",
        "ConflictError",
        "ValidationError",
    ):
        cls = getattr(M, name)
        assert isinstance(cls, type)
        assert issubclass(cls, errors.ManageError)


def test_facade_re_exports_the_same_objects():
    # the facade is a true re-export, not a copy
    assert M.create_rubric is rubric_crud.create_rubric
    assert M.reorder_criteria is rubric_crud.reorder_criteria
    assert M.list_prompts is prompt_crud.list_prompts
    assert M.delete_prompt is prompt_crud.delete_prompt
    assert M.ConflictError is errors.ConflictError
    assert M.ManageError is errors.ManageError
