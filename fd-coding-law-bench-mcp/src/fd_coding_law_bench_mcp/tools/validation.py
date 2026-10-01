"""Compliance-validation tools (read + check).

Wrap :mod:`src.validations.validate` and the ``type_validations`` table.
These are a standalone compliance layer — NOT wired into generation or
assembly. ``validation_list`` browses stored constraints for a type;
``validation_check`` evaluates a draft + slot dict against them.
"""

from __future__ import annotations

import anyio

from ..server import mcp


@mcp.tool(tags={"validations"})
async def validation_list(contract_type: str) -> list[dict]:
    """List stored validation constraints for a contract type.

    Parameters:
        contract_type: law-bench contract class key (e.g. ``"sale"``).

    Returns constraint dicts (``constraint_id, kind, field, message,
    severity, law_ref``) from the ``type_validations`` table, already
    merged by the loader (inheritance resolved at load time). An empty
    list means no validation file exists for this type.
    """
    from src.eval.db import connect

    def _go() -> list[dict]:
        conn = connect(None)
        rows = conn.execute(
            "SELECT constraint_id, kind, field, message, "
            "severity, law_ref, inherited_from, params "
            "FROM type_validations WHERE contract_type = %s ORDER BY id",
            (contract_type,),
        ).fetchall()
        return [dict(r) for r in rows]

    return await anyio.to_thread.run_sync(_go)


@mcp.tool(tags={"validations"})
async def validation_check(
    contract_type: str,
    draft: str | None = None,
    slots: dict | None = None,
) -> dict:
    """Evaluate a drafted contract against legal hard-limit constraints.

    Parameters:
        contract_type: law-bench contract class key (e.g. ``"sale"``).
        draft: assembled contract markdown string (may be ``None``).
        slots: dict ``{slot_name: value}`` from the assembled contract.

    Returns ``{errors: [...], warnings: [...], passed: bool}``. Each entry
    is ``{constraint_id, message, law_ref, severity}``. ``passed`` is True
    when there are no errors (warnings do not block). This is a post-hoc
    compliance check — it does not affect generation or assembly.
    """
    from src.validations.validate import validate_draft

    def _go() -> dict:
        return validate_draft(contract_type, draft=draft, slots=slots)

    return await anyio.to_thread.run_sync(_go)
