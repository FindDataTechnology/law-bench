#!/usr/bin/env python3
"""Generate per-type Chinese slot manifest from masters/*.yaml.

Reads the 84 master files and maps them to the 66 contract_types.json keys.
For each type, extracts required_fields and emits a slot manifest with Chinese
slot names (field ids), labels, descriptions, examples, required flags, and a
``latin`` field carrying the old Latin canonical name where one exists (so the
Latin->Chinese render map in slot_ontology can bridge DB clauses that still
carry Latin slots).

Output: src/contracts/data/type_slots.json
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
CT_PATH = REPO / "src/eval/seed/law_info/contract_types.json"
MASTERS_DIR = REPO / "contract-generator/合同生成规则/masters"
OUT_PATH = REPO / "src/contracts/data/type_slots.json"

# Generic Chinese slot set for types with no backing master. These are the 12
# canonical concepts rendered with Chinese slot names so the "all slots Chinese"
# guarantee holds even without a per-type master. `latin` preserves the old
# Latin canonical name so the render map can bridge DB clauses still carrying
# Latin slots.
GENERIC_CN_SLOTS = [
    {"name": "甲方名称", "latin": "party_a", "label": "甲方名称", "description": "合同甲方的全称或姓名", "example": "北京甲科技有限公司", "required": True, "source": "party_a"},
    {"name": "乙方名称", "latin": "party_b", "label": "乙方名称", "description": "合同乙方的全称或姓名", "example": "北京乙贸易有限公司", "required": True, "source": "party_b"},
    {"name": "合同标的", "latin": "subject", "label": "合同标的", "description": "本合同的具体标的、事宜或范围描述", "example": "合同的具体标的与内容", "required": True, "source": "both"},
    {"name": "价款金额", "latin": "amount", "label": "价款金额", "description": "合同价款或费用金额（数字）", "example": "100000", "required": True, "source": "both"},
    {"name": "履行起始日期", "latin": "term_start", "label": "履行起始日期", "description": "合同履行开始日期", "example": "2026-01-01", "required": True, "source": "both"},
    {"name": "履行结束日期", "latin": "term_end", "label": "履行结束日期", "description": "合同履行结束日期", "example": "2026-12-31", "required": True, "source": "both"},
    {"name": "甲方义务", "latin": "party_a_duty", "label": "甲方义务", "description": "甲方在本合同项下的主要义务", "example": "按期交付标的物并转移所有权", "required": True, "source": "party_a"},
    {"name": "乙方义务", "latin": "party_b_duty", "label": "乙方义务", "description": "乙方在本合同项下的主要义务", "example": "按期足额支付价款", "required": True, "source": "party_b"},
    {"name": "违约金", "latin": "penalty", "label": "违约金", "description": "违约金数额或计算方式", "example": "合同价款的10%", "required": False, "source": "both"},
    {"name": "争议解决方式", "latin": "jurisdiction", "label": "争议解决方式", "description": "争议解决方式及管辖/仲裁机构", "example": "提交原告所在地人民法院诉讼解决", "required": False, "source": "both"},
    {"name": "签署日期", "latin": "sign_date", "label": "签署日期", "description": "合同签署日期", "example": "2026-01-01", "required": True, "source": "both"},
    {"name": "签署地点", "latin": "sign_location", "label": "签署地点", "description": "合同签署地点", "example": "北京市朝阳区", "required": False, "source": "both"},
]

# Keyword -> Latin canonical concept. First match wins; checked against the
# field id (Chinese). Lets a master field carry a `latin` bridge so the render
# map can map old Latin corpus slots (party_a, amount, ...) to the per-type
# Chinese name. Fields that match no keyword get latin=null (type-specific
# Chinese slot with no Latin counterpart — stays Chinese, no bridging).
_LATIN_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("甲方",), "party_a"),
    (("乙方",), "party_b"),
    (("标的", "租赁物", "抵押物", "房屋坐落", "设备清单", "车辆"), "subject"),
    (("价款", "金额", "租金", "报酬", "费用", "借款金额", "服务费", "赔偿总额"), "amount"),
    (("起始", "开始", "起租", "开工"), "term_start"),
    (("结束", "终止", "届满", "到期", "竣工", "完成"), "term_end"),
    (("交付", "验收"), "party_a_duty"),
    (("付款", "还款", "支付"), "party_b_duty"),
    (("违约",), "penalty"),
    (("争议", "管辖", "仲裁"), "jurisdiction"),
    (("签署日期", "签订日期", "签约日期"), "sign_date"),
    (("签署地点", "签订地点", "签约地点"), "sign_location"),
]


def _match_latin(fid: str, source: str) -> str | None:
    """Map a Chinese field id to a Latin canonical concept, or None."""
    if source == "party_a" and ("甲方" in fid or "名称" in fid and "乙" not in fid):
        # only treat as the party name when it reads like a name field
        if "甲方" in fid or fid.endswith("名称"):
            return "party_a"
    if source == "party_b" and ("乙方" in fid or fid.endswith("名称")):
        return "party_b"
    for kws, latin in _LATIN_KEYWORDS:
        if any(k in fid for k in kws):
            return latin
    return None


# Manual mapping for types that don't stem-match but zh-name-match
ZH_NAME_MAP = {
    "bailment": "deposit",
    "construction": "project",
    "employment": "labor",
    "entrustment": "mandate",
    "equity_holding_in_trust": "nominee-holding",
    "financing_lease": "lease.financing",
    "intermediation": "brokerage",
    "property_service": "property",
    "real_estate_lease": "lease.immovable.house",
    "tourism_service": "tourism",
    "warehousing": "storage",
    "equity_transfer": "equity-transfer",
    "real_estate_sale": "sale.real-estate",
    "labor_dispatch": "labor-dispatch",
    "land_transfer": "rural-land",
    "utilities_supply": "utility",
}


def _load_master(stem: str) -> dict | None:
    p = MASTERS_DIR / f"{stem}.yaml"
    if not p.is_file():
        return None
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _master_to_slots(master: dict, zh: str) -> list[dict]:
    """Convert a master's required_fields to slot instructions.

    Every emitted slot name is Chinese: a Chinese field id (e.g. ``借款金额``)
    is used verbatim; a Latin-shaped id (e.g. labor.yaml's ``employer_name``)
    is rendered through its Chinese ``name`` label so the "all slots Chinese"
    guarantee holds for every master, including the labor outlier.
    """
    slots = []
    seen: set[str] = set()
    for f in master.get("required_fields") or []:
        fid = f.get("id") or f.get("key") or f.get("name") or ""
        if not fid:
            continue
        # Latin-shaped id -> surface its Chinese `name` label as the slot name.
        latin_id = fid if (fid.isascii() and ("_" in fid or fid.islower())) else None
        slot_name = (f.get("name") or fid) if latin_id is not None else fid
        # A slot name must match the {{\w+}} token regex used by the generator,
        # coherence gate, and audit. Chinese names containing separators like
        # "业委会/业主大会" or "交付/登记" are sanitized to the first segment
        # ( 业委会 / 交付 ) so the placeholder stays a single \w+ word.
        if not re.fullmatch(r"\w+", slot_name):
            slot_name = re.sub(r"[^\w]+", "", slot_name) or slot_name
        if slot_name in seen:
            continue
        seen.add(slot_name)
        source = f.get("source") or "both"
        # Bridge to a canonical Latin concept only when the Chinese name reads
        # like one of the 12 (so DB clauses carrying {{party_a}} etc. can be
        # rendered into the new Chinese name at assembly time).
        latin = _match_latin(slot_name, source)
        ftype = f.get("type") or "text"
        example = _example_for(ftype, zh, slot_name)
        slots.append({
            "name": slot_name,  # Chinese slot name
            "latin": latin,
            "label": f.get("name") or slot_name,
            "description": f.get("prompt") or "",
            "example": example,
            "required": not f.get("defer", False),
            "source": source,
        })
    return slots


def _example_for(ftype: str, zh: str, fid: str) -> str:
    """A best-effort example value from the field's type/contract."""
    if ftype.startswith("money"):
        return "100000"
    if ftype.startswith("number"):
        return "1"
    if ftype.startswith("date"):
        return "2026-06-30"
    if ftype.startswith("duration"):
        return "12个月"
    if ftype.startswith("enum"):
        opts = ftype.split("{", 1)[-1].rstrip("}").split(",")
        return opts[0].strip() if opts and opts[0] else ""
    if "名称" in fid:
        return "北京甲科技有限公司"
    if "日期" in fid or "时间" in fid:
        return "2026-06-30"
    return f"{zh}的具体内容"


def main() -> int:
    ct = json.loads(CT_PATH.read_text(encoding="utf-8"))
    registry = []
    matched = 0
    fallback = 0

    for t in ct:
        key = t["key"]
        zh = t["zh"]

        master_stem = key
        master = _load_master(master_stem)

        if master is None and key in ZH_NAME_MAP:
            master_stem = ZH_NAME_MAP[key]
            master = _load_master(master_stem)

        if master is not None:
            slots = _master_to_slots(master, zh)
            if slots:
                registry.append({
                    "type": key, "zh": zh, "slots": slots,
                    "source": f"masters/{master_stem}.yaml",
                })
                matched += 1
                continue

        registry.append({
            "type": key, "zh": zh, "slots": GENERIC_CN_SLOTS,
            "source": "generic-chinese-fallback",
        })
        fallback += 1

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(registry)} type slot manifests to {OUT_PATH}")
    print(f"  matched masters: {matched}")
    print(f"  generic fallback: {fallback}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
