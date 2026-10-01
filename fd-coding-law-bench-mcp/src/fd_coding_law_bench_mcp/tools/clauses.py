"""Clause management tools (read + write).

Wrap :mod:`src.clauses.store` (list / get / update / delete) and
:mod:`src.clauses.tag_review` (bulk approve/reject). These are the MCP
write surface for clauses - the existing ``search_clauses`` tool is RAG
retrieval over chunked clause text, whereas ``clause_list`` browses the
``clauses`` table directly by type / category / tags.

Every ``NotFoundError`` / ``ValidationError`` from the store layer surfaces as
a tool error (no swallowing), mirroring :mod:`tools.rubrics`.
``clause_update`` rebuilds the store's ``fields`` dict from the non-``None``
parameters so omitted fields are left untouched. ``clause_review`` sets all of
a clause's tag dims to one status; a clause becomes assembly-ineligible when
any dim is not ``"approved"`` (so ``"rejected"`` excludes it from assembly).
"""

from __future__ import annotations

import anyio

from ..server import mcp


@mcp.tool(tags={"clauses"})
async def clause_list(
    contract_type: str | None = None,
    category: str | None = None,
    tags: dict | None = None,
    q: str | None = None,
) -> list[dict]:
    """List clauses from the ``clauses`` table, filtered and ordered.

    Parameters:
        contract_type: contract class key (e.g. ``"sale"``); ``None`` for all.
        category: ``tags.source`` filter - ``"base"`` / ``"tagged"`` / ``"custom"``.
        tags: dim filters, e.g. ``{"scenario": "农产品买卖", "stance": "balanced"}``;
            each ``dim->value`` becomes ``tags->>'dim' = 'value'``.
        q: case-insensitive substring over ``body`` and ``source_doc_title``.

    Returns clause dicts (``id, contract_type, section, body, tags, tag_review,
    slot_instructions, law_refs, ...``) ordered by section rank then id.
    """
    from src.clauses.store import list_clauses

    def _go() -> list[dict]:
        return list_clauses(contract_type, category=category, tags=tags, q=q)

    return await anyio.to_thread.run_sync(_go)


@mcp.tool(tags={"clauses"})
async def clause_get(clause_id: int) -> dict | None:
    """Fetch one clause by id (any source: base / tagged / custom).

    Parameters:
        clause_id: clause id.

    Returns the clause dict, or ``None`` if no clause has that id.
    """
    from src.clauses.store import get_custom_clause

    return await anyio.to_thread.run_sync(get_custom_clause, clause_id)


@mcp.tool(tags={"clauses"})
async def clause_update(
    clause_id: int,
    body: str | None = None,
    section: str | None = None,
    tags: dict | None = None,
) -> dict:
    """Update a clause's body / section / tags by id; re-derives dependent fields.

    Only the parameters you pass are written; omitted fields keep their current
    value. ``body_hash`` / ``slot_instructions`` / ``law_refs`` are re-derived
    from the (possibly edited) body. The clause is marked ``manual=true`` so a
    later re-extraction won't overwrite the edit. Raises a tool error for an
    unknown id.

    Parameters:
        clause_id: id of the clause to update.
        body: new clause body (Markdown, may carry ``{{slot}}`` placeholders).
        section: new section heading (e.g. ``"权利义务"``).
        tags: replacement tag dict (curatorial - replaces, not merges).

    Returns the updated clause dict.
    """
    from src.clauses.store import update_clause

    fields = {
        k: v
        for k, v in (("body", body), ("section", section), ("tags", tags))
        if v is not None
    }

    def _go() -> dict:
        return update_clause(clause_id, fields)

    return await anyio.to_thread.run_sync(_go)


@mcp.tool(tags={"clauses"})
async def clause_delete(clause_id: int) -> dict:
    """Delete one clause by id.

    Parameters:
        clause_id: id of the clause to delete.

    Returns ``{deleted: True, clause_id}``. Raises a tool error for an unknown id.
    """
    from src.clauses.store import delete_clause

    await anyio.to_thread.run_sync(delete_clause, clause_id)
    return {"deleted": True, "clause_id": clause_id}


@mcp.tool(tags={"clauses"})
async def clause_review(clause_id: int, status: str) -> dict:
    """Set ALL of a clause's tag dims to one review status (bulk approve/reject).

    A clause is assembly-ready only when every tag dim is ``"approved"``; setting
    any dim to ``"rejected"`` (or ``"pending"``) excludes it from assembly, so a
    thin custom clause can be retired without deleting it (re-approve later to
    restore it).

    Parameters:
        clause_id: id of the clause to review.
        status: ``"pending"`` / ``"approved"`` / ``"rejected"``.

    Returns ``{reviewed: True, clause_id, status}``. An invalid status or an
    unknown id raises a tool error.
    """
    from src.clauses.tag_review import bulk_review

    def _go() -> None:
        bulk_review(clause_id, status)

    await anyio.to_thread.run_sync(_go)
    return {"reviewed": True, "clause_id": clause_id, "status": status}
