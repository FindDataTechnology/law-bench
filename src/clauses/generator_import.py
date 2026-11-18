"""Import contract-generator rules into law-bench via the generator's own loader.

Reuses :class:`contract_rules.loader.RulesRegistry` (chain / elements_for /
clauses_for / validations_for) — the loader already implements inheritance,
dedup, and field-level merge, so we never re-parse the YAMLs ad hoc.

Additions: idempotent re-import (``tag_review`` ``_source_hash`` stamps) and
slot_instructions enrichment (``prompt``/``type``/``enum_values``).
"""

from __future__ import annotations

import hashlib
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# generator package lives outside law-bench's src tree; put its parent on sys.path
# parents[0]=clauses  parents[1]=src  parents[2]=law-template
_GENERATOR_ROOT = Path(__file__).resolve().parents[2] / "contract-generator" / "合同生成规则"
if str(_GENERATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_GENERATOR_ROOT))

from contract_rules.loader import RulesRegistry, _build_registry  # noqa: E402

RULES_DIR = _GENERATOR_ROOT / "contract_rules" / "rules"


def _source_hash() -> str:
    """MD5 over all elements/clauses/validation YAMLs — drift fingerprint."""
    h = hashlib.md5()
    for sub in ("elements", "clauses", "validation"):
        d = RULES_DIR / sub
        if not d.exists():
            continue
        for p in sorted(d.glob("*.yaml")):
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def build_registry() -> tuple[RulesRegistry, str]:
    """Instantiate the generator's RulesRegistry (sync) + rules-dir source hash."""
    return _build_registry(), _source_hash()


# generator clause title → law-bench SECTION_ORDER bucket (best-effort)
_TITLE_KEYWORDS = (
    ("当事人", "当事人"), ("标的", "合同标的"), ("金额", "价款及支付"),
    ("价款", "价款及支付"), ("付款", "价款及支付"), ("费用", "价款及支付"),
    ("期限", "履行期限"), ("交付", "履行期限"), ("履行", "履行期限"),
    ("权利", "权利义务"), ("义务", "权利义务"), ("违约", "违约责任"),
    ("争议", "争议解决"), ("通知", "争议解决"), ("附则", "附则"), ("签署", "签署信息"),
)


def section_from_title(title: str) -> str:
    t = (title or "").strip()
    for kw, sec in _TITLE_KEYWORDS:
        if kw in t:
            return sec
    return t or "附则"


# ── Task 7: slot_instructions enrichment ──────────────────────────────────

def _parse_element_type(raw: str | None) -> tuple[str, list[str] | None]:
    """Parse a generator element ``type`` string into (base_type, enum_values).

    ``enum{A, B}`` → ``("enum", ["A", "B"])``; ``duration{months}`` →
    ``("duration", None)``; ``money`` → ``("money", None)``;
    ``list[{name, brand}]`` → ``("list", None)``.
    """
    if not raw:
        return "text", None
    base = raw.split("{", 1)[0].strip()
    if base == "enum":
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            inner = raw[start + 1:end]
            vals = [v.strip() for v in inner.split(",") if v.strip()]
            return "enum", vals
    return base, None


def _slot_instructions_for(contract_type: str, registry: RulesRegistry) -> list[dict]:
    """Build slot_instructions from generator elements (enriched 8-key form).

    Element ``id`` is the ``{{slot}}`` name used in clause bodies, so every body
    slot is covered and the coherence gate passes. Enriched with ``prompt``
    (大白话问法), ``type`` (money|enum|date|duration|text|number|list), and
    ``enum_values`` (only when type==enum). Field-level inheritance (loan
    redefining 甲方名称→甲方(出借人)名称 while inheriting required/type) is
    already resolved by the loader's ``elements_for()`` field-merge —
    ``e.get("name")`` is the per-type label, so NO extra per-type override
    code is needed.
    """
    out: list[dict] = []
    for e in registry.elements_for(contract_type):
        base_type, enum_vals = _parse_element_type(e.get("type"))
        entry: dict[str, Any] = {
            "name": e.get("id"),
            "label": e.get("name") or e.get("id"),
            "description": e.get("prompt") or "",
            "example": "",
            "required": bool(e.get("required", False)),
        }
        prompt = e.get("prompt")
        if prompt:
            entry["prompt"] = prompt
        if base_type:
            entry["type"] = base_type
        if base_type == "enum" and enum_vals:
            entry["enum_values"] = enum_vals
        out.append(entry)
    return out


# ── Task 6: idempotency + drift ────────────────────────────────────────────

def clause_records(
    contract_type: str,
    registry: RulesRegistry | None = None,
    source_hash: str | None = None,
) -> list[dict]:
    """Build law-bench clause dicts (ready for ``upsert_clause``) from generator rules.

    ``source_path`` is keyed ``generator://<type>/<clause_id>`` so re-runs hit the
    upsert conflict clause (idempotent). ``tag_review`` stamps
    ``_source_hash`` (the ``build_registry()`` hash) and ``_imported_at`` (ISO
    timestamp) for drift detection — stored in the free-form jsonb field, NOT
    passed through ``validate_tags``, so no tags.py or DDL change is needed.
    ``upsert_clause``'s ON CONFLICT DO UPDATE does not refresh ``tag_review``,
    but that's fine: a changed YAML changes the body → new ``body_hash`` → new
    row (no conflict) → fresh hash; unchanged YAML → same hash → no false drift.
    """
    if registry is None:
        registry, source_hash = build_registry()
    elif source_hash is None:
        source_hash = _source_hash()
    now_iso = datetime.now().isoformat()
    instructions = _slot_instructions_for(contract_type, registry)
    out: list[dict] = []
    for c in registry.clauses_for(contract_type):
        body = (c.get("text") or "").strip()
        if not body:
            continue
        out.append({
            "contract_type": contract_type,
            "section": section_from_title(c.get("title")),
            "body": body,
            "slot_instructions": instructions,
            "source_path": f"generator://{contract_type}/{c.get('id')}",
            "source_doc_title": c.get("source") or "",
            "tags": {"source": "base"},
            "category": "base",
            "tag_review": {"_source_hash": source_hash, "_imported_at": now_iso},
        })
    return out


def import_type(
    contract_type: str,
    db: Any = None,
    dry_run: bool = True,
    registry: RulesRegistry | None = None,
) -> dict:
    """Upsert generator clauses for one type; return ``{written, skipped, ids}``.

    ``dry_run=True`` (default) prints actions without writing — safe smoke test.
    """
    records = clause_records(contract_type, registry)
    if dry_run:
        for r in records:
            print(f"[DRY] {contract_type}/{r['section']}: {r['body'][:50]}…")
        return {"written": 0, "skipped": len(records), "ids": []}

    from src.clauses.store import upsert_clause
    ids: list[int] = []
    for r in records:
        ids.append(upsert_clause(r, db))
    return {"written": len(ids), "skipped": 0, "ids": ids}
