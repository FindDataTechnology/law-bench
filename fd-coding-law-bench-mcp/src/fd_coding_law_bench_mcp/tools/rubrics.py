"""Rubric & criterion management tools.

Wrap the local-authored CRUD in :mod:`src.eval.rubric_crud`. Harbor rubrics
(``source LIKE 'harbor:%'``) stay read-only - the guard lives in
``rubric_crud`` and the resulting :class:`HarborReadOnlyError` propagates to the
MCP client as a tool error (no second guard here). Every ``ManageError``
(``NotFoundError`` / ``ConflictError`` / ``ValidationError`` /
``HarborReadOnlyError``) surfaces as a tool error rather than being swallowed.
"""

from __future__ import annotations

import anyio

from ..server import mcp


@mcp.tool(tags={"rubrics"})
async def rubric_get(name: str) -> dict:
    """Fetch a rubric's metadata and ordered criteria, by name.

    Parameters:
        name: rubric name (e.g. ``"contract_sale_v1"``).

    Returns ``{id, name, context, source, source_path, description, created_at,
    is_harbor, criterion_count, criteria}``. An unknown name raises a tool
    error.
    """
    from src.eval.rubric_crud import get_rubric_detail

    return await anyio.to_thread.run_sync(get_rubric_detail, name)


@mcp.tool(tags={"rubrics"})
async def rubric_create(
    name: str,
    context: str,
    description: str | None = None,
    criteria: list[dict] | None = None,
) -> dict:
    """Create a local rubric (``source = 'local'``) with optional criteria.

    Parameters:
        name: unique local rubric name.
        context: non-empty context (e.g. ``"contract"``).
        description: optional human description.
        criteria: optional list of ``{name, description, guidance}`` dicts.

    Returns the new rubric detail. A duplicate local name or a bad criterion
    raises a tool error. Harbor rubrics cannot be created here (they are
    seeded, not authored).
    """
    from src.eval.rubric_crud import create_rubric as _create

    def _go() -> dict:
        return _create(name, context, description=description, criteria=criteria)

    return await anyio.to_thread.run_sync(_go)


@mcp.tool(tags={"rubrics"})
async def rubric_update(
    rubric_id: int,
    name: str,
    context: str,
    description: str | None = None,
) -> dict:
    """Update a local rubric's name, context, and description (criteria untouched).

    Parameters:
        rubric_id: id of the rubric to update.
        name: new name.
        context: new non-empty context.
        description: new optional description.

    Returns the updated rubric detail. Writing to a harbor rubric raises a tool
    error.
    """
    from src.eval.rubric_crud import update_rubric as _update

    def _go() -> dict:
        return _update(rubric_id, name, context, description=description)

    return await anyio.to_thread.run_sync(_go)


@mcp.tool(tags={"rubrics"})
async def rubric_delete(rubric_id: int) -> dict:
    """Delete a local rubric; its criteria cascade via FK ON DELETE CASCADE.

    Parameters:
        rubric_id: id of the rubric to delete.

    Returns ``{deleted: True, rubric_id}``. Deleting a harbor rubric raises a
    tool error.
    """
    from src.eval.rubric_crud import delete_rubric as _delete

    await anyio.to_thread.run_sync(_delete, rubric_id)
    return {"deleted": True, "rubric_id": rubric_id}


@mcp.tool(tags={"rubrics"})
async def criterion_add(
    rubric_id: int,
    name: str,
    description: str,
    guidance: str,
) -> dict:
    """Append a criterion to a local rubric at the next ordinal.

    Parameters:
        rubric_id: id of the rubric to extend.
        name: unique-within-rubric criterion name.
        description: what is checked.
        guidance: the ``PASS if ... / FAIL if ...`` standard the judge uses.

    Returns the new criterion record. Writing to a harbor rubric raises a tool
    error.
    """
    from src.eval.rubric_crud import add_criterion as _add

    def _go() -> dict:
        return _add(rubric_id, name, description, guidance)

    return await anyio.to_thread.run_sync(_go)


@mcp.tool(tags={"rubrics"})
async def criterion_update(
    criterion_id: int,
    name: str,
    description: str,
    guidance: str,
) -> dict:
    """Update a criterion's name, description, and guidance (ordinal untouched).

    Parameters:
        criterion_id: id of the criterion to update.
        name: new unique-within-rubric name.
        description: new description.
        guidance: new guidance.

    Returns the updated criterion record. Editing a criterion on a harbor
    rubric raises a tool error.
    """
    from src.eval.rubric_crud import update_criterion as _update

    def _go() -> dict:
        return _update(criterion_id, name, description, guidance)

    return await anyio.to_thread.run_sync(_go)


@mcp.tool(tags={"rubrics"})
async def criterion_delete(criterion_id: int) -> dict:
    """Delete a criterion from a local rubric and renumber the survivors.

    Parameters:
        criterion_id: id of the criterion to delete.

    Returns ``{deleted: True, criterion_id}``. Deleting a criterion on a harbor
    rubric raises a tool error.
    """
    from src.eval.rubric_crud import delete_criterion as _delete

    await anyio.to_thread.run_sync(_delete, criterion_id)
    return {"deleted": True, "criterion_id": criterion_id}


@mcp.tool(tags={"rubrics"})
async def criterion_reorder(rubric_id: int, ordered_criterion_ids: list[int]) -> list[int]:
    """Reassign criterion ``ordinal`` to match the given order.

    Parameters:
        rubric_id: id of the rubric whose criteria are reordered.
        ordered_criterion_ids: every current criterion id, once each, in the
            new order.

    Returns the applied id order. A list that is not exactly the rubric's
    current criterion ids raises a validation tool error. Reordering a harbor
    rubric raises a tool error.
    """
    from src.eval.rubric_crud import reorder_criteria as _reorder

    def _go() -> list[int]:
        return _reorder(rubric_id, ordered_criterion_ids)

    return await anyio.to_thread.run_sync(_go)
