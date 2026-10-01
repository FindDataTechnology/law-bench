"""Generate contract DOCX/PDF deliverables from templates via ``src/docs/``."""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.generator import create_docx, docx_to_pdf

from .legal import extract_laws_for_type
from .slots import get_slot_instructions
from .templates import _REPO_ROOT, get_template

_FORMATS = ("docx", "pdf", "both")


def generate_contract(
    contract_type: str, *, format: str = "pdf", out_dir: str | Path | None = None
) -> dict:
    """Generate the contract deliverable(s) for ``contract_type``.

    ``format`` is ``"docx"``, ``"pdf"``, or ``"both"``. Files are written under
    ``out_dir`` (default ``output/contracts``). Every ``{{slot}}`` is rendered as
    a highlighted, fillable placeholder (no slot is pre-filled). Returns
    ``{docx_path, pdf_path, slots, instructions, laws}`` where formats not
    requested map to ``None``. Raises :class:`NotFoundError` for an unknown type.
    """
    if format not in _FORMATS:
        raise ValueError(f"unsupported format: {format!r}; use one of {_FORMATS}")

    template = get_template(contract_type)
    instructions = get_slot_instructions(contract_type)
    laws = extract_laws_for_type(contract_type)

    out = Path(out_dir) if out_dir else _REPO_ROOT / "output" / "contracts"
    out.mkdir(parents=True, exist_ok=True)

    body = template["body"]
    title = template["zh_name"]
    docx_path: Path | None = None
    pdf_path: Path | None = None

    if format == "docx":
        docx_path = out / f"{contract_type}.docx"
        create_docx(body, str(docx_path), title=title, slot_style="literal")
    elif format == "both":
        docx_path = out / f"{contract_type}.docx"
        pdf_path = out / f"{contract_type}.pdf"
        create_docx(body, str(docx_path), title=title, slot_style="literal")
        docx_to_pdf(str(docx_path), output_path=str(pdf_path))
    else:  # pdf (build the DOCX in a temp dir so only the PDF lands in out_dir)
        pdf_path = out / f"{contract_type}.pdf"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_docx = Path(tmp) / f"{contract_type}.docx"
            create_docx(body, str(tmp_docx), title=title, slot_style="literal")
            docx_to_pdf(str(tmp_docx), output_path=str(pdf_path))

    return {
        "docx_path": str(docx_path) if docx_path else None,
        "pdf_path": str(pdf_path) if pdf_path else None,
        "body_text": body,
        "slots": template["slots"],
        "instructions": instructions,
        "laws": laws,
    }
