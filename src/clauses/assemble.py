"""Assemble a contract from base + scenario-tagged + custom clauses.

The assembly model is **per-section override with extension**:

- For each section exactly one clause body is rendered, resolved by precedence
  ``custom(stance) > tagged(scenario) > base(母版)``. Base is the fallback for
  any section no override targets.
- A tagged/custom clause whose ``section`` is absent from the 母版 is
  **extended** into the contract at a canonical position (before ``附则``).
- Within a single source, if multiple clauses target the same section, one is
  picked by a documented tiebreak (``manual`` > most slots > longest body >
  lowest id) and the section is flagged heuristic-sourced in the diagnostics.

The resolved contract passes a :mod:`src.clauses.coherence` gate before
rendering. Every ``{{slot}}`` is rendered as a highlighted, fillable
placeholder (no slot is pre-filled).
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

from src.contracts.slots import REQUIRED_SLOTS, default_slot_instructions
from src.contracts.slot_ontology import render_body_chinese, render_instructions_chinese
from src.contracts.templates import list_contract_types
from src.generator import SLOT_PATTERN, ConverterNotAvailableError, create_docx, docx_to_pdf
from src.eval.errors import NotFoundError
from src.eval.legal_refs import CATEGORY_ORDER

from .coherence import CoherenceError, validate_coherence
from .extract import SECTION_ORDER
from .store import get_custom_clause, list_clauses
from .tag_review import is_assembly_ready

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FORMATS = ("markdown", "docx", "pdf", "both")
# Extended (non-canonical) sections rank just before 附则 so they land after the
# canonical body and before the closing 附则/签署信息 sections.
_EXT_RANK = SECTION_ORDER.index("附则") - 0.5
_SLOT_RE = re.compile(r"\{\{(\w+)\}\}")


def _zh_name(contract_type: str) -> str:
    for t in list_contract_types():
        if t["key"] == contract_type:
            return t["zh"]
    return contract_type


def _slots_in(body: str) -> set[str]:
    return set(_SLOT_RE.findall(body or ""))


def _pick_variant(clauses: list[dict]) -> dict:
    """Tiebreak within one (source, section): manual > most slots > longest body > lowest id."""
    return min(
        clauses,
        key=lambda c: (
            0 if c.get("manual") else 1,
            -len(_slots_in(c.get("body") or "")),
            -len((c.get("body") or "").strip()),
            c["id"],
        ),
    )


def _section_sort_key(section: str) -> tuple[float, str]:
    if section in SECTION_ORDER:
        return (float(SECTION_ORDER.index(section)), "")
    return (_EXT_RANK, section)


def _resolve_sections(
    base: list[dict], tagged: list[dict], custom: list[dict]
) -> tuple[list[dict], list[str], set[str]]:
    """Resolve one clause per section by precedence custom > tagged > base.

    Returns ``(resolved, heuristic_sections, base_sections)``. ``resolved`` is
    ordered by canonical section rank (extended sections before ``附则``).
    ``heuristic_sections`` lists sections where a within-source tiebreak fired.
    ``base_sections`` is the set of sections the 母版 defines (for the gate).
    """
    groups: dict[str, dict[str, list[dict]]] = {}
    for src, clauses in (("base", base), ("tagged", tagged), ("custom", custom)):
        for c in clauses:
            groups.setdefault(c["section"], {"base": [], "tagged": [], "custom": []})[src].append(c)

    base_sections = {c["section"] for c in base}
    resolved: list[dict] = []
    heuristic: list[str] = []
    for section, g in groups.items():
        for src in ("custom", "tagged", "base"):  # precedence high -> low
            if g[src]:
                resolved.append(_pick_variant(g[src]))
                if len(g[src]) > 1:
                    heuristic.append(section)
                break

    resolved.sort(key=lambda c: _section_sort_key(c["section"]))
    return resolved, heuristic, base_sections


def _select_clauses(
    contract_type: str,
    scenario: str | None,
    custom_clause_ids: list[int] | None,
    stance: str | None = None,
    db: Any = None,
) -> tuple[list[dict], list[str], set[str]]:
    """Collect base/tagged/custom candidates and resolve them per section.

    Tagged clauses are filtered by ``scenario``; custom clauses by ``stance``
    (or by explicit ``custom_clause_ids``), and only assembly-ready customs are
    eligible. Returns the override-resolved clause list + diagnostics.
    """
    base = list_clauses(contract_type, category="base", db=db)
    tagged = (
        list_clauses(contract_type, category="tagged", tags={"scenario": scenario}, db=db)
        if scenario
        else []
    )
    if custom_clause_ids:
        custom: list[dict] = []
        for cid in custom_clause_ids:
            c = get_custom_clause(cid, db=db)
            if c is not None and is_assembly_ready(c) and (
                stance is None or (c.get("tags") or {}).get("stance") == stance
            ):
                custom.append(c)
    elif stance:
        candidates = list_clauses(contract_type, category="custom", tags={"stance": stance}, db=db)
        custom = [c for c in candidates if is_assembly_ready(c)]
    else:
        custom = []

    return _resolve_sections(base, tagged, custom)


def _assemble_body(clauses: list[dict]) -> str:
    """Render one body per resolved clause, in section order (no concatenation)."""
    parts: list[str] = []
    for c in clauses:
        body = (c.get("body") or "").strip()
        if body:
            parts.append(f"## {c['section']}\n\n{body}")
    return "\n\n".join(parts).strip()


def _build_instructions(clauses: list[dict], zh: str, contract_type: str | None = None) -> list[dict]:
    """12 canonical slot instructions ∪ clause-declared slots ∪ ontology fallback.

    Deduped by name. Any body slot still lacking an instruction is looked up in
    the slot ontology (:mod:`src.contracts.slot_ontology`) so the coherence gate's
    "every slot must be instructed" check passes for real contracts.
    """
    from src.contracts.slot_ontology import instruction_for_slot

    instructions: list[dict] = []
    names: set[str] = set()
    for ins in default_slot_instructions(zh):
        if ins["name"] not in names:
            names.add(ins["name"])
            instructions.append(dict(ins))
    for c in clauses:
        for ins in c.get("slot_instructions") or []:
            if ins.get("name") and ins["name"] not in names:
                names.add(ins["name"])
                instructions.append(
                    {
                        "name": ins["name"],
                        "label": ins.get("label") or ins["name"],
                        "description": ins.get("description") or "",
                        "example": ins.get("example") or "",
                        "required": bool(ins.get("required", False)),
                    }
                )
    # ontology fallback: cover body slots with no declared instruction
    body_slots: set[str] = set()
    for c in clauses:
        body_slots |= _slots_in(c.get("body") or "")
    for slot in sorted(body_slots):
        if slot not in names:
            ins = instruction_for_slot(slot, contract_type)
            if ins:
                names.add(slot)
                instructions.append(ins)
    return instructions


def _build_law_refs(clauses: list[dict]) -> list[dict]:
    """Deduped union of clause law_refs, sorted by (category order, name)."""
    by_name: dict[str, dict] = {}
    for c in clauses:
        for ref in c.get("law_refs") or []:
            name = ref.get("name")
            if name and name not in by_name:
                by_name[name] = ref
    return sorted(
        by_name.values(),
        key=lambda r: (CATEGORY_ORDER.index(r["category"]) if r.get("category") in CATEGORY_ORDER else len(CATEGORY_ORDER), r.get("name", "")),
    )


def generate_contract_assembled(
    contract_type: str,
    *,
    scenario: str | None = None,
    custom_clause_ids: list[int] | None = None,
    stance: str | None = None,
    format: str = "docx",
    out_dir: str | Path | None = None,
    db: Any = None,
) -> dict:
    """Assemble and render a contract from base + tagged + custom clauses.

    The contract is resolved by per-section override (``custom > tagged >
    base``) with base fallback and section extension, then passes the coherence
    gate before rendering. ``format`` is ``"docx"`` (default), ``"pdf"``,
    ``"markdown"`` (text only, no file I/O), or ``"both"``; files are written
    under ``out_dir`` (default ``output/contracts``). Every ``{{slot}}`` is
    rendered
    as a highlighted, fillable placeholder. Returns
    ``{docx_path, pdf_path, body_text, title, slots, instructions, law_refs,
    diagnostics}``
    where unrequested formats map to ``None`` and ``diagnostics.heuristic_sections``
    lists sections resolved by a within-source tiebreak. Raises
    :class:`NotFoundError` for an unknown contract type and
    :class:`CoherenceError` if the resolved contract fails the coherence gate.
    ``db`` is an optional borrowed connection; left None, the store opens its own.
    """
    if format not in _FORMATS:
        raise ValueError(f"unsupported format: {format!r}; use one of {_FORMATS}")
    valid_keys = {t["key"] for t in list_contract_types()}
    if contract_type not in valid_keys:
        raise NotFoundError(f"unknown contract type: {contract_type!r}")

    zh = _zh_name(contract_type)
    resolved, heuristic, base_sections = _select_clauses(
        contract_type, scenario, custom_clause_ids, stance, db=db
    )
    body = _assemble_body(resolved)
    # Render Latin canonical slots -> per-type Chinese display names so every
    # generated contract carries Chinese slots ({{甲方名称}}, {{借款金额}}, ...).
    # Both body and instructions are rendered together so the coherence gate's
    # name-match check (body slot == instruction name) stays consistent.
    body = render_body_chinese(body, contract_type)
    instructions = _build_instructions(resolved, zh, contract_type)
    instructions = render_instructions_chinese(instructions, contract_type)
    law_refs = _build_law_refs(resolved)
    slots = list(dict.fromkeys(SLOT_PATTERN.findall(body)))

    validate_coherence(resolved, body, instructions, base_sections)

    out = Path(out_dir) if out_dir else _REPO_ROOT / "output" / "contracts"
    out.mkdir(parents=True, exist_ok=True)

    docx_path: Path | None = None
    pdf_path: Path | None = None
    base_name = contract_type if not scenario else f"{contract_type}__{scenario}"
    if format == "markdown":
        # Content-only path: no file I/O, fastest return
        pass
    elif format == "docx":
        docx_path = out / f"{base_name}.docx"
        create_docx(body, str(docx_path), title=zh, slot_style="literal")
    elif format == "both":
        docx_path = out / f"{base_name}.docx"
        pdf_path = out / f"{base_name}.pdf"
        create_docx(body, str(docx_path), title=zh, slot_style="literal")
        docx_to_pdf(str(docx_path), output_path=str(pdf_path))
    else:  # pdf
        pdf_path = out / f"{base_name}.pdf"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_docx = Path(tmp) / f"{base_name}.docx"
            create_docx(body, str(tmp_docx), title=zh, slot_style="literal")
            docx_to_pdf(str(tmp_docx), output_path=str(pdf_path))

    return {
        "docx_path": str(docx_path) if docx_path else None,
        "pdf_path": str(pdf_path) if pdf_path else None,
        "title": zh,
        "body_text": body,
        "slots": slots,
        "instructions": instructions,
        "law_refs": law_refs,
        "diagnostics": {"heuristic_sections": heuristic},
    }
