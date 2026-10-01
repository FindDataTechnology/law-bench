"""Contract content API - direct markdown/JSON returns without file I/O.

Wraps generate_contract_assembled to return body_text, slots, instructions,
law_refs directly without DOCX/PDF generation. Format enum: "markdown" (default),
"docx", "pdf", "both". Content-first path enables real-time API consumption.
"""

from __future__ import annotations

import anyio
import uuid
from typing import Literal

from ..server import mcp


@mcp.tool(tags={"contracts"})
async def contract_content(
    contract_type: str,
    tags: dict | None = None,
    stance: str | None = None,
    format: Literal["markdown", "docx", "pdf", "both"] = "markdown",
    include_current_tags: bool = False,
    trace_id: str | None = None,
) -> dict:
    """Return assembled contract content (markdown/JSON) without file I/O.

    Parameters:
        contract_type: contract class key, e.g. ``"sale"`` or ``"employment"``.
        tags: optional dict; recognized keys are ``stance`` and ``scenario``.
            Other keys are ignored.
        stance: convenience for ``tags["stance"]``.
        format: return format: ``"markdown"`` (body text only, default), ``"docx"``,
            ``"pdf"``, or ``"both"``. Markdown mode is fastest (no file rendering).
        include_current_tags: when True, attach live tag vocabulary from DB.
        trace_id: optional tracing ID for debugging batch failures.

    Returns ``{trace_id, contract_type, format, body_text, slots, instructions,
    law_refs, tags_used}`` where ``body_text`` is assembled markdown with
    ``{{slot}}`` placeholders. If format is docx/pdf, adds paths; if markdown
    only, returns immediately without file I/O. Raises NotFoundError for unknown
    contract type or CoherenceError if assembly fails coherence gate.

    Example:
    ```python
    result = await contract_content(
        "sale",
        tags={"scenario": "农产品买卖", "stance": "balanced"},
        format="markdown"
    )
    # result.body_text contains assembled markdown instantly
    ```
    """
    from src.clauses.assemble import generate_contract_assembled
    from src.clauses.tags import load_vocab_from_db, tag_vocab_for_type, validate_tags
    from src.eval.errors import NotFoundError

    # Derive effective stance + scenario from tags param
    scenario = None
    if tags:
        cleaned_tags = validate_tags(tags, contract_type)
        stance = stance or cleaned_tags.get("stance")
        scenario = cleaned_tags.get("scenario")
    else:
        cleaned_tags = {}

    def _go() -> dict:
        trace = trace_id or str(uuid.uuid4())

        try:
            result = generate_contract_assembled(
                contract_type,
                scenario=scenario,
                stance=stance,
                format=format,  # pass through to control file rendering
            )

            response = {
                "trace_id": trace,
                "contract_type": contract_type,
                "format": format,
                "body_text": result.get("body_text"),
                "slots": result.get("slots", []),
                "instructions": result.get("instructions", []),
                "law_refs": result.get("law_refs", []),
                "tags_used": cleaned_tags if cleaned_tags else {},
            }

            # Add file paths if requested
            if format != "markdown":
                response["docx_path"] = result.get("docx_path")
                response["pdf_path"] = result.get("pdf_path")

            if include_current_tags:
                load_vocab_from_db()
                response["current_tags"] = tag_vocab_for_type(contract_type)

            return response

        except NotFoundError as e:
            raise ValueError(f"unknown contract type: {contract_type!r}") from e

        except Exception as e:
            # CoherenceError, etc. - propagate with trace id
            raise ValueError(f"contract assembly failed: {e}") from e

    # ponytail: thread-pool only for DB-bound part; content-only path fast
    return await anyio.to_thread.run_sync(_go)
