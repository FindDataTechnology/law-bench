"""``contract_generate`` tool.

Wraps :func:`src.contracts.generate_contract` (skeleton 母版 template) and
:func:`src.clauses.assemble.generate_contract_assembled` (base + tagged + custom
clause assembly). When ``include_current_tags`` is set, attaches the live
custom-tag vocabulary (starter + ``tag_dims`` + any runtime-registered dims).
"""

from __future__ import annotations

import anyio

from ..server import mcp


@mcp.tool(tags={"contracts"})
async def contract_generate(
    contract_type: str,
    format: str = "pdf",
    tags: dict | None = None,
    stance: str | None = None,
    out_dir: str | None = None,
    include_current_tags: bool = False,
    custom_clause_ids: list[int] | None = None,
) -> dict:
    """Generate a contract deliverable (DOCX/PDF) for a contract class.

    By default renders the registered 母版 template (skeleton). When ``stance``
    and/or a ``tags`` dict carrying ``stance`` / ``scenario`` is supplied,
    assembles base + tagged + custom clauses and filters the custom-clause
    selection by the given stance (``pro_a`` / ``pro_b`` / ``balanced``) and the
    tagged selection by scenario (业务场景, e.g. 农产品买卖 / 驾校培训 /
    住宅租赁). ``region`` / ``province`` keys are not recognized (province was
    retired in favor of ``scenario``).

    Parameters:
        contract_type: contract class key, e.g. ``"sale"`` or ``"employment"``.
        format: ``"docx"`` / ``"pdf"`` / ``"both"`` (default ``"pdf"``).
        tags: optional dict; recognized keys are ``stance`` and ``scenario``.
            Other keys (including ``region``/``province``) are ignored.
        stance: convenience for ``tags["stance"]``.
        out_dir: output directory (default ``output/contracts``).
        include_current_tags: when True, attach ``current_tags`` - the live
            custom-tag vocabulary (starter set + ``tag_dims`` + any dims
            registered in-process via ``register_tag_dim``), so the caller can
            see which tag values are currently available.
        custom_clause_ids: optional explicit custom-clause id list forwarded to
            ``generate_contract_assembled`` (assembly path only). Use it to
            select / exclude specific custom clauses per call (e.g. a
            self-healing loop dropping a thin override) without mutating the
            shared ``clauses`` table. Ignored for the skeleton path. ``None``
            preserves the default selection (backward-compatible).

    Returns ``{docx_path, pdf_path, body_text, slots, instructions, ...}`` where
    ``body_text`` is the assembled Markdown body with ``{{slot}}`` placeholders;
    the skeleton path also includes ``laws`` and the assembled path includes
    ``law_refs``; plus ``current_tags`` when requested. An unknown
    ``contract_type`` raises a tool error.
    """
    from src.clauses.assemble import generate_contract_assembled
    from src.contracts import generate_contract

    # Derive the effective stance + scenario. The underlying assembler only
    # filters custom clauses by `stance` and tagged clauses by `scenario`, so we
    # surface exactly those two dimensions from `tags`.
    if tags:
        stance = stance or tags.get("stance")
        scenario = tags.get("scenario")
    else:
        scenario = None

    def _go() -> dict:
        if stance or scenario:
            result = generate_contract_assembled(
                contract_type,
                scenario=scenario,
                stance=stance,
                format=format,
                out_dir=out_dir,
                custom_clause_ids=custom_clause_ids,
            )
        else:
            result = generate_contract(contract_type, format=format, out_dir=out_dir)

        if include_current_tags:
            from src.clauses.tags import load_vocab_from_db, tag_vocab_for_type

            # Merge tag_dims into the live TAG_VOCAB (idempotent, best-effort:
            # degrades to the starter set if the DB is unreachable), then expose the
            # flat per-type vocabulary - universal dims + this contract_type's dims,
            # including any runtime-registered temporary dim - as a simple
            # dim -> [allowed values] mapping. ``tag_vocab_for_type`` returns a fresh
            # dict, so the caller cannot mutate the server's process vocabulary.
            load_vocab_from_db()
            result["current_tags"] = tag_vocab_for_type(contract_type)

        return result

    return await anyio.to_thread.run_sync(_go)
