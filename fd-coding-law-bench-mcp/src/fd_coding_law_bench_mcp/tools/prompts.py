"""Generation-prompt management tools.

Wrap the local-only prompt CRUD in :mod:`src.eval.prompt_crud`. Prompts are
always locally authored and freely editable (no harbor analog, no read-only
guard). ``NotFoundError`` / ``ConflictError`` / ``ValidationError`` surface as
tool errors.
"""

from __future__ import annotations

import anyio

from ..server import mcp


@mcp.tool(tags={"prompts"})
async def prompt_list() -> list[dict]:
    """List all generation prompts (without the content body).

    Returns ``[{id, name, contract_type, purpose, source, prompt_type,
    description, created_at}]``.
    """
    from src.eval.prompt_crud import list_prompts as _list

    return await anyio.to_thread.run_sync(_list)


@mcp.tool(tags={"prompts"})
async def prompt_get(name: str) -> dict:
    """Fetch a prompt's full record (including ``content``), by name.

    Parameters:
        name: prompt name.

    Returns ``{id, name, contract_type, purpose, content, source, prompt_type,
    description, created_at}``. An unknown name raises a tool error.
    """
    from src.eval.prompt_crud import get_prompt as _get

    return await anyio.to_thread.run_sync(_get, name)


@mcp.tool(tags={"prompts"})
async def prompt_create(
    name: str,
    contract_type: str,
    purpose: str,
    content: str,
    description: str | None = None,
    prompt_type: str | None = None,
) -> dict:
    """Create a local prompt (``source = 'local'``).

    Parameters:
        name: unique prompt name.
        contract_type: contract class key this prompt drafts for.
        purpose: short purpose label.
        content: the drafting instruction text.
        description: optional human description.
        prompt_type: optional type tag (e.g. ``"baseline"``).

    Returns the new prompt record. A duplicate name or blank field raises a
    tool error.
    """
    from src.eval.prompt_crud import create_prompt as _create

    def _go() -> dict:
        return _create(
            name, contract_type, purpose, content,
            description=description, prompt_type=prompt_type,
        )

    return await anyio.to_thread.run_sync(_go)


@mcp.tool(tags={"prompts"})
async def prompt_update(
    prompt_id: int,
    name: str,
    contract_type: str,
    purpose: str,
    content: str,
    description: str | None = None,
    prompt_type: str | None = None,
) -> dict:
    """Update a prompt's full record.

    Parameters:
        prompt_id: id of the prompt to update.
        name, contract_type, purpose, content: new values (all required).
        description: new optional description.
        prompt_type: new optional type tag.

    Returns the updated prompt record. An unknown id or a duplicate name raises
    a tool error.
    """
    from src.eval.prompt_crud import update_prompt as _update

    def _go() -> dict:
        return _update(
            prompt_id, name, contract_type, purpose, content,
            description=description, prompt_type=prompt_type,
        )

    return await anyio.to_thread.run_sync(_go)


@mcp.tool(tags={"prompts"})
async def prompt_delete(prompt_id: int) -> dict:
    """Delete a prompt (no child table, nothing cascades).

    Parameters:
        prompt_id: id of the prompt to delete.

    Returns ``{deleted: True, prompt_id}``. An unknown id raises a tool error.
    """
    from src.eval.prompt_crud import delete_prompt as _delete

    await anyio.to_thread.run_sync(_delete, prompt_id)
    return {"deleted": True, "prompt_id": prompt_id}
