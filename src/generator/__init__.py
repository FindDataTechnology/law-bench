"""Document generation: DOCX creation with slots + DOCX -> PDF conversion.

Public API:

- :func:`create_docx` - render Markdown content to a ``.docx`` with slots.
- :func:`add_slot` - append a slot to an existing document.
- :func:`fill_slots` / :func:`find_slots` / :func:`slot_token` - slot helpers.
- :func:`docx_to_pdf` / :func:`get_converter` - PDF output.
"""

from __future__ import annotations

from .converter import (
    ConverterNotAvailableError,
    Docx2PdfConverter,
    HttpRenderConverter,
    LibreOfficeConverter,
    PdfConverter,
    docx_to_pdf,
    get_converter,
)
from .generator import add_slot, create_docx
from .slots import SLOT_PATTERN, SlotValueError, fill_slots, find_slots, slot_token

__all__ = [
    "SLOT_PATTERN",
    "SlotValueError",
    "ConverterNotAvailableError",
    "PdfConverter",
    "LibreOfficeConverter",
    "Docx2PdfConverter",
    "HttpRenderConverter",
    "slot_token",
    "find_slots",
    "fill_slots",
    "create_docx",
    "add_slot",
    "docx_to_pdf",
    "get_converter",
]
