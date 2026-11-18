"""Contract-template routes: ``/contracts`` (browse), ``/contracts/{type}``
(template + slots + slot instructions + per-type 法律法规), and
``/contracts/{type}/download/{format}`` (DOCX/PDF via ``src.contracts``).

Read-only HTML pages backed by the file-backed ``src.contracts`` API (shared
with the CLI) - no database. Markdown bodies are rendered server-side.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from ..templating import templates as _templates
from ..markdown_render import render_markdown
from ...contracts import (
    extract_laws_for_type,
    generate_contract,
    get_slot_instructions,
    get_template,
    list_contract_types,
)
from ...generator import ConverterNotAvailableError
from ...eval.errors import NotFoundError
from ...eval.legal_refs import CATEGORY_ORDER, CATEGORY_ZH

router = APIRouter(tags=["contracts"])


@router.get("/contracts", include_in_schema=False, name="page_contracts")
def contracts_list(request: Request):
    types = list_contract_types()
    return _templates.TemplateResponse(
        request, "contracts_list.html", {"types": types}
    )


@router.get("/contracts/{contract_type}", include_in_schema=False, name="page_contract_detail")
def contract_detail(request: Request, contract_type: str):
    try:
        template = get_template(contract_type)
        instructions = get_slot_instructions(contract_type)
        laws = extract_laws_for_type(contract_type)
    except NotFoundError:
        return _templates.TemplateResponse(
            request,
            "contract_detail.html",
            {
                "not_found": True,
                "contract_type": contract_type,
                "template": None,
                "instructions": [],
                "grouped": [],
                "body_html": "",
            },
            status_code=404,
        )
    grouped = [
        {
            "category": cat,
            "category_zh": CATEGORY_ZH[cat],
            "refs": [l for l in laws if l["category"] == cat],
        }
        for cat in CATEGORY_ORDER
    ]
    grouped = [g for g in grouped if g["refs"]]
    return _templates.TemplateResponse(
        request,
        "contract_detail.html",
        {
            "not_found": False,
            "contract_type": contract_type,
            "template": template,
            "instructions": instructions,
            "grouped": grouped,
            "body_html": render_markdown(template["body"]),
        },
    )


@router.get(
    "/contracts/{contract_type}/download/{format}",
    include_in_schema=False,
    name="page_contract_download",
)
def contract_download(contract_type: str, format: str):
    if format not in ("docx", "pdf"):
        raise HTTPException(status_code=400, detail="unsupported format; use docx or pdf")
    try:
        result = generate_contract(contract_type, format=format)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"unknown contract type: {contract_type}")
    except ConverterNotAvailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    path = result["docx_path"] if format == "docx" else result["pdf_path"]
    if path is None:
        raise HTTPException(status_code=500, detail="document generation failed")
    media = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if format == "docx"
        else "application/pdf"
    )
    return FileResponse(path, media_type=media, filename=f"{contract_type}.{format}")
