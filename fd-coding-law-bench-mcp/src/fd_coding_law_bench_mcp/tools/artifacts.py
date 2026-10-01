"""Stored-artifact MCP tools (generate-and-store + download).

Wrap :mod:`src.contracts.artifacts` so an MCP agent can generate a contract,
persist it to MinIO + the ``contract_artifacts`` DB table, and later fetch its
metadata / download URL without regenerating. Mirrors the HTTP endpoints under
``/api/contracts/...``; bytes are fetched over HTTP (MCP returns metadata +
URLs, not binary streams).
"""

from __future__ import annotations

import anyio

from ..server import mcp


def _urls(artifact_id: int, row: dict) -> dict[str, str]:
    """Map each stored format/variant to its HTTP download path."""
    out: dict[str, str] = {}
    for fmt in ("docx", "pdf"):
        if row.get(f"{fmt}_key"):
            out[fmt] = f"/api/contracts/artifacts/{artifact_id}/download?format={fmt}"
        if row.get(f"{fmt}_key_slotted"):
            out[f"{fmt}_slotted"] = (
                f"/api/contracts/artifacts/{artifact_id}/download?format={fmt}&variant=slotted"
            )
    return out


@mcp.tool(tags={"contracts"})
async def contract_generate_stored(
    contract_type: str,
    format: str = "docx",
    tags: dict | None = None,
    stance: str | None = None,
    custom_clause_ids: list[int] | None = None,
) -> dict:
    """Generate a contract deliverable (DOCX/PDF), upload it to MinIO, and record
    a ``contract_artifacts`` row so it can be re-downloaded without regenerating.

    Content-addressed by ``md5(body_text)``: identical inputs (same
    ``contract_type`` + ``scenario`` + ``stance`` + ``custom_clause_ids``) reuse
    the same artifact (``reused: true``); missing formats are filled in.

    Parameters:
        contract_type: contract class key, e.g. ``"sale"``.
        format: ``"docx"`` (default) / ``"pdf"`` / ``"both"`` / ``"markdown"``.
            ``"markdown"`` stores the body text only (no file upload).
        tags: optional dict; recognized keys are ``stance`` and ``scenario``
            (convenience: ``stance`` may also be passed directly). When **omitted**
            (and no ``stance``/``custom_clause_ids``), generates **every**
            scenario x stance x base combination for the type.
        stance: convenience for ``tags["stance"]``.
        custom_clause_ids: optional explicit custom-clause id list for assembly.

    Returns a single-variant dict ``{artifact_id, docx_url, pdf_url, body_text,
    slots, reused}`` when any tag is given, or a summary dict
    ``{contract_type, format, artifacts: [...], count, new, reused, failed,
    failures}`` when generating by contract type (no tags). ``docx_url``/
    ``pdf_url`` are HTTP download paths
    (``/api/contracts/artifacts/{id}/download?format=...``) or ``null`` when the
    format was not produced. An unknown ``contract_type`` raises a tool error.
    """
    from src.contracts.artifacts import generate_all_stored, generate_stored

    # The underlying assembler filters custom clauses by `stance` and tagged
    # clauses by `scenario`, so surface exactly those two dims from `tags`.
    if tags:
        stance = stance or tags.get("stance")
        scenario = tags.get("scenario")
    else:
        scenario = None

    if scenario or stance or custom_clause_ids:
        def _go() -> dict:
            return generate_stored(
                contract_type,
                scenario=scenario,
                stance=stance,
                custom_clause_ids=custom_clause_ids,
                format=format,
            )
    else:
        def _go() -> dict:
            return generate_all_stored(contract_type, format=format)

    return await anyio.to_thread.run_sync(_go)


@mcp.tool(tags={"contracts"})
async def contract_download(
    artifact_id: int, format: str | None = None, variant: str = "final"
) -> dict | None:
    """Fetch a stored contract artifact's metadata + download URL(s).

    Does NOT regenerate - it reads the previously-stored ``contract_artifacts``
    row. The agent fetches the file bytes over HTTP from the returned URL.

    Parameters:
        artifact_id: the id returned by ``contract_generate_stored``.
        format: when set (``"docx"`` or ``"pdf"``), also include a top-level
            ``download_url`` for that format (``null`` if not stored).
        variant: ``"final"`` (default, finished 成品) or ``"slotted"``
            (fillable template with ``{{slot}}`` tokens). Only affects the
            top-level ``download_url`` when ``format`` is set.

    Returns ``{artifact_id, contract_type, scenario, stance, body_text, slots,
    docx_key, pdf_key, docx_key_slotted, pdf_key_slotted, created_at,
    download_urls, download_url?}``, or ``None`` if no artifact has that id.
    """
    from src.contracts.artifacts import get_artifact

    def _go() -> dict | None:
        row = get_artifact(artifact_id)
        if row is None:
            return None
        urls = _urls(artifact_id, row)
        result = {
            "artifact_id": artifact_id,
            "contract_type": row["contract_type"],
            "scenario": row.get("scenario"),
            "stance": row.get("stance"),
            "body_text": row.get("body_text"),
            "slots": row.get("slots"),
            "docx_key": row.get("docx_key"),
            "pdf_key": row.get("pdf_key"),
            "docx_key_slotted": row.get("docx_key_slotted"),
            "pdf_key_slotted": row.get("pdf_key_slotted"),
            "created_at": row.get("created_at"),
            "download_urls": urls,
        }
        if format:
            key = f"{format}_slotted" if variant == "slotted" else format
            result["download_url"] = urls.get(key)
        return result

    return await anyio.to_thread.run_sync(_go)
