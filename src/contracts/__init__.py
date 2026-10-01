"""Contract template generation: extract 法律法规, build slot-based templates
with slot instructions, and generate DOCX/PDF deliverables.

Public API:

- :func:`list_contract_types` / :func:`get_template` - contract class registry.
- :func:`get_slot_instructions` / :func:`check_slot_consistency` - slot docs.
- :func:`extract_laws_for_type` - per-class 法律法规 extraction.
- :func:`generate_contract` - DOCX/PDF generation via ``src.generator``.
- :func:`audit_template` / :func:`audit_body` / :func:`audit_all` - slot
  completeness evaluator for contract 母版 (deterministic, no LLM/DB).
"""

from __future__ import annotations

from .audit import AuditReport, TemplateAudit, audit_all, audit_body, audit_template
from .generator import generate_contract
from .legal import extract_laws_for_type
from .slots import check_slot_consistency, get_slot_instructions
from .templates import get_template, list_contract_types

__all__ = [
    "list_contract_types",
    "get_template",
    "get_slot_instructions",
    "check_slot_consistency",
    "extract_laws_for_type",
    "generate_contract",
    "audit_template",
    "audit_body",
    "audit_all",
    "TemplateAudit",
    "AuditReport",
]
