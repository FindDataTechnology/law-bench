#!/usr/bin/env python3
"""Backfill contract templates for types present in ``contract_types.json`` but
absent from the template registry ``src/contracts/data/contracts.json``.

Why this exists: ``contract_types.json`` grew to 66 types when the Category B
generator rules were integrated, but the template registry only ever got the 54
that had 母版 (masters) sources. Nothing noticed because the repo had no test
gate — ``list_contract_types()`` returned 66 while ``get_template()`` raised
``NotFoundError`` for 12 of them.

The slot manifest is NOT invented here: ``src/contracts/data/type_slots.json``
already carries per-type Chinese slots for all 66 types (built from the
masters). This script derives the body from that manifest, so a backfilled
template is exactly as specific as its slot data — no placeholder slots.

Idempotent: only types missing from the registry are appended; existing
entries are left byte-for-byte untouched. Re-running is a no-op.

Run:
    uv run python scripts/backfill_missing_templates.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

TYPES_PATH = REPO_ROOT / "src" / "eval" / "seed" / "law_info" / "contract_types.json"
REGISTRY_PATH = REPO_ROOT / "src" / "contracts" / "data" / "contracts.json"
TYPE_SLOTS_PATH = REPO_ROOT / "src" / "contracts" / "data" / "type_slots.json"

# A generic 民法典 skeleton whose slots come from the type's own manifest. The
# clause headings are the ones every 民法典 contract shares (标的/价款/期限/
# 权利义务/违约/争议/附则), so the body stays valid for any type; what differs
# per type is which Chinese slots fill it.
#
# Every slot the body carries MUST come from the type's own manifest: the audit
# (src/contracts/audit.py::audit_template) treats a body that carries per-type
# Chinese tokens as a Chinese skeleton and audits it against that type's own
# slot set. Mixing in Latin tokens would route it down the legacy Latin branch
# and report every Chinese slot as an orphan.
_BODY_TEMPLATE = """\
甲方：%PARTY_A%
乙方：%PARTY_B%

鉴于甲乙双方就%ZH%事宜，经友好协商，依据《中华人民共和国民法典》及相关法律法规，本着平等自愿、诚实信用的原则，达成如下协议，以资共同遵守。

## 第一条 合同标的

%SUBJECT%

## 第二条 价款及支付

%AMOUNT%

## 第三条 履行期限

%TERM%

## 第四条 双方权利义务

%DUTIES%

## 第五条 违约责任

%PENALTY%

## 第六条 争议解决

%JURISDICTION%

## 第七条 附则

1. 本合同自双方签字（盖章）之日起生效。
2. 本合同一式两份，甲乙双方各执一份，具有同等法律效力。

%SIGNING%
"""

# Latin bridge -> the clause of the skeleton that slot belongs in.
_LATIN_SECTION = {
    "party_a": "PARTY_A",
    "party_b": "PARTY_B",
    "subject": "SUBJECT",
    "amount": "AMOUNT",
    "term_start": "TERM",
    "term_end": "TERM",
    "party_a_duty": "DUTIES",
    "party_b_duty": "DUTIES",
    "penalty": "PENALTY",
    "jurisdiction": "JURISDICTION",
    "sign_date": "SIGNING",
    "sign_location": "SIGNING",
}

_SECTION_LEAD = {
    "PARTY_A": "甲方",
    "PARTY_B": "乙方",
    "SUBJECT": "本合同标的",
    "AMOUNT": "本合同价款",
    "TERM": "本合同履行期限",
    "DUTIES": "",
    "PENALTY": "",
    "JURISDICTION": "",
    "SIGNING": "",
}

# Fallback sentence per section, used only when the type's manifest has no slot
# bridged to that section (e.g. a type with no 价款 clause). A backfilled
# template must still read as a contract, not as a form with holes.
_SECTION_FALLBACK = {
    "SUBJECT": "本合同标的由双方另行书面确认。",
    "AMOUNT": "本合同价款及支付方式由双方另行书面确认。",
    "TERM": "本合同履行期限由双方另行书面确认。",
    "DUTIES": "1. 甲方应按约定履行本合同项下的义务。\n2. 乙方应按约定履行本合同项下的义务。",
    "PENALTY": "任何一方违反本合同约定，应向守约方赔偿因此遭受的实际损失。",
    "JURISDICTION": "因本合同引起的争议，双方应友好协商解决；协商不成的，提交有管辖权的人民法院诉讼解决。",
    "SIGNING": "签署日期：____年__月__日\n签署地点：________",
}


def _section_lines(slots: list[dict], section: str) -> str:
    """Clause body for ``section``, covering every type slot bridged to it.

    Duty slots read as a numbered list; every other section reads as a
    ``label：{{slot}}`` list. Slots with no Latin bridge (``latin`` is None) are
    type-specific content — 保密信息范围, 投资方式, 赔偿明细 — so they belong in
    the 标的 section; leaving them out would put them in the manifest with no
    place in the body, which the audit reports as orphans. Returns the fallback
    sentence when the type has no slot for that section.
    """
    names = [
        s["name"]
        for s in slots
        if _LATIN_SECTION.get(s.get("latin")) == section
        or (section == "SUBJECT" and s.get("latin") is None)
    ]
    if not names:
        return _SECTION_FALLBACK[section]
    if section == "DUTIES":
        return "\n".join(f"{i}. 主要义务：{{{{{n}}}}}。" for i, n in enumerate(names, 1))
    if section == "SIGNING":
        return "\n".join(f"{n}：{{{{{n}}}}}" for n in names)
    lead = _SECTION_LEAD.get(section) or section
    return "；".join(f"{n}：{{{{{n}}}}}" for n in names) + "。"


def build_entry(key: str, zh: str, slots: list[dict]) -> dict:
    """Build one registry entry from the type's own slot manifest."""
    body = _BODY_TEMPLATE.replace("%ZH%", zh)
    for section in ("PARTY_A", "PARTY_B", "SUBJECT", "AMOUNT", "TERM",
                    "DUTIES", "PENALTY", "JURISDICTION", "SIGNING"):
        body = body.replace(f"%{section}%", _section_lines(slots, section))
    instructions = [
        {
            "name": s["name"],
            "label": s.get("label") or s["name"],
            "description": s.get("description") or "",
            "example": s.get("example") or "",
            "required": bool(s.get("required")),
        }
        for s in slots
    ]
    return {"key": key, "zh": zh, "body": body, "slot_instructions": instructions}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report without writing")
    args = ap.parse_args()

    types = json.loads(TYPES_PATH.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    type_slots = {e["type"]: e for e in json.loads(TYPE_SLOTS_PATH.read_text(encoding="utf-8"))}

    have = {e["key"] for e in registry}
    missing = [t for t in types if t["key"] not in have]
    if not missing:
        print(f"nothing to do: all {len(types)} contract types have a template")
        return 0

    added = []
    for t in missing:
        key, zh = t["key"], t["zh"]
        slots = type_slots.get(key, {}).get("slots") or []
        if not slots:
            print(f"  SKIP {key}: no slot manifest in type_slots.json", file=sys.stderr)
            continue
        registry.append(build_entry(key, zh, slots))
        added.append(key)

    print(f"adding {len(added)} template(s): {', '.join(added)}")
    if args.dry_run:
        print("(dry run — nothing written)")
        return 0

    REGISTRY_PATH.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote {len(registry)} templates to {REGISTRY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
