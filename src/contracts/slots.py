"""Slot-instruction model for contract templates.

A *slot instruction* documents a single ``{{slot}}`` placeholder: what it is,
how to fill it, an example, and whether it is required. Instructions are
generated alongside the templates into ``src/contracts/data/contracts.json``
and live in this contracts layer (they are not a change to ``document-generation``).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from src.eval.errors import NotFoundError

from .templates import _registry, get_template


def get_slot_instructions(contract_type: str) -> list[dict]:
    """Return the slot-instruction manifest for ``contract_type``.

    A list of ``{name, label, description, example, required}``. Raises
    :class:`NotFoundError` for an unknown type.
    """
    entry = _registry().get(contract_type)
    if entry is None:
        raise NotFoundError(f"unknown contract type: {contract_type!r}")
    return [dict(si) for si in entry.get("slot_instructions", [])]


def check_slot_consistency(contract_type: str) -> tuple[list[str], list[str]]:
    """Return ``(missing_instructions, extra_instructions)`` for ``contract_type``.

    ``missing_instructions`` lists template slots without an instruction;
    ``extra_instructions`` lists instructions for slots absent from the template.
    A consistent template has both lists empty.
    """
    template_slots = set(get_template(contract_type)["slots"])
    instr_names = {si["name"] for si in get_slot_instructions(contract_type)}
    missing = sorted(template_slots - instr_names)
    extra = sorted(instr_names - template_slots)
    return missing, extra


# The canonical slot set + default instruction manifest for contract templates.
# Single source of truth shared by scripts/seed_contract_templates.py (skeleton)
# and scripts/generate_contract_templates_llm.py (type-specific) so they stay in
# sync. The 12 names MUST match the {{slot}} tokens used in the template bodies.
REQUIRED_SLOTS = (
    "party_a", "party_b", "subject", "amount", "term_start", "term_end",
    "party_a_duty", "party_b_duty", "penalty", "jurisdiction",
    "sign_date", "sign_location",
)


def default_slot_instructions(zh: str) -> list[dict]:
    """The default slot-instruction manifest for a contract of type ``zh``.

    The ``subject`` example is tailored to the contract type; the rest are shared.
    """
    subject_example = f"{zh}的具体标的与内容"
    return [
        {"name": "party_a", "label": "甲方名称", "description": "合同甲方（通常为标的提供方/服务方）的全称或姓名", "example": "北京甲科技有限公司", "required": True},
        {"name": "party_b", "label": "乙方名称", "description": "合同乙方的全称或姓名", "example": "北京乙贸易有限公司", "required": True},
        {"name": "subject", "label": "合同标的", "description": "本合同的具体标的、事宜或范围描述", "example": subject_example, "required": True},
        {"name": "amount", "label": "价款金额", "description": "合同价款或费用金额（数字）", "example": "100000", "required": True},
        {"name": "term_start", "label": "履行起始日期", "description": "合同履行开始日期", "example": "2026-01-01", "required": True},
        {"name": "term_end", "label": "履行结束日期", "description": "合同履行结束日期", "example": "2026-12-31", "required": True},
        {"name": "party_a_duty", "label": "甲方义务", "description": "甲方在本合同项下的主要义务", "example": "按期交付标的物并转移所有权", "required": True},
        {"name": "party_b_duty", "label": "乙方义务", "description": "乙方在本合同项下的主要义务", "example": "按期足额支付价款", "required": True},
        {"name": "penalty", "label": "违约金", "description": "违约金数额或计算方式", "example": "合同价款的10%", "required": False},
        {"name": "jurisdiction", "label": "争议解决方式", "description": "争议解决方式及管辖/仲裁机构", "example": "提交原告所在地人民法院诉讼解决", "required": False},
        {"name": "sign_date", "label": "签署日期", "description": "合同签署日期", "example": "2026-01-01", "required": True},
        {"name": "sign_location", "label": "签署地点", "description": "合同签署地点", "example": "北京市朝阳区", "required": False},
    ]


# ---------------------------------------------------------------------------
# Per-type Chinese slot manifest (masters/*.yaml -> data/type_slots.json)
# ---------------------------------------------------------------------------
# The 母版 required_fields become the per-type slot source so every generated
# contract carries Chinese slot names ({{甲方名称}}, {{借款金额}}, ...). Each slot
# carries a ``latin`` bridge to the old Latin canonical concept so the render map
# in slot_ontology can rewrite DB clauses that still carry Latin slots
# ({{party_a}} -> {{甲方名称}}) at assembly time, without migrating the corpus.
_HERE = Path(__file__).resolve().parent
_TYPE_SLOTS_PATH = _HERE / "data" / "type_slots.json"


@lru_cache(maxsize=1)
def _type_slots_registry() -> dict[str, dict]:
    """Load and cache the per-type Chinese slot manifest keyed by contract type.

    Returns ``{type_key: {type, zh, slots, source}}``. Empty dict when the
    manifest file is absent (legacy/development without a generated manifest).
    """
    if not _TYPE_SLOTS_PATH.is_file():
        return {}
    with _TYPE_SLOTS_PATH.open(encoding="utf-8") as fh:
        return {e["type"]: e for e in json.load(fh)}


def required_slots_for_type(contract_type: str) -> list[str]:
    """Return the per-type slot names (Chinese) for ``contract_type``.

    This is the per-type analogue of :data:`REQUIRED_SLOTS` — the full slot set
    the contract class defines, used by the seeder/audit/normalize to know which
    slots belong. Falls back to the Latin :data:`REQUIRED_SLOTS` when no
    per-type manifest exists, so callers always get a usable slot set.
    """
    entry = _type_slots_registry().get(contract_type)
    if entry is None:
        return list(REQUIRED_SLOTS)
    return [s["name"] for s in entry.get("slots", [])]


def slot_instructions_for_type(contract_type: str, zh: str | None = None) -> list[dict]:
    """Return the per-type slot-instruction manifest (Chinese slot names).

    Each dict is ``{name, label, description, example, required}`` plus the
    bridging ``latin`` and ``source`` fields. Falls back to
    :func:`default_slot_instructions` when no per-type manifest exists.
    """
    entry = _type_slots_registry().get(contract_type)
    if entry is None:
        return default_slot_instructions(zh or "")
    out: list[dict] = []
    for s in entry.get("slots", []):
        out.append({
            "name": s["name"],
            "label": s.get("label") or s["name"],
            "description": s.get("description") or "",
            "example": s.get("example") or "",
            "required": bool(s.get("required", False)),
            "latin": s.get("latin"),
            "source": s.get("source", "both"),
        })
    return out


def latin_to_chinese_map(contract_type: str) -> dict[str, str]:
    """Latin canonical concept -> per-type Chinese slot name.

    Built from the per-type manifest's ``latin`` bridge fields (first bridge
    wins). Used by the slot-ontology render pass to rewrite Latin slots in DB
    clause bodies to their Chinese display names at assembly time. Empty for
    types with no manifest (callers fall back to the generic Latin set).
    """
    entry = _type_slots_registry().get(contract_type)
    if entry is None:
        return {}
    m: dict[str, str] = {}
    for s in entry.get("slots", []):
        latin = s.get("latin")
        if latin and latin not in m:
            m[latin] = s["name"]
    return m


def tail_allowed_slots_for_type(contract_type: str) -> list[str]:
    """Per-type slot names that may legitimately appear only in the 签署信息 tail.

    These are the per-type slots bridged from the Latin ``sign_date`` /
    ``sign_location`` concepts (签署日期 / 签署地点). Returns an empty list for
    per-type manifests that define no signing slots (nothing to tail-allow).
    Callers that need a universal fallback should fall back to the Latin
    :data:`REQUIRED_SLOTS` tail pair when this returns ``[]`` for a type with no
    manifest.
    """
    entry = _type_slots_registry().get(contract_type)
    if entry is None:
        return ["sign_date", "sign_location"]
    return [
        s["name"]
        for s in entry.get("slots", [])
        if s.get("latin") in ("sign_date", "sign_location")
    ]
