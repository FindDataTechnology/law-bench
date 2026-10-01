"""Pure extractor that aggregates the 法律法规 referenced across law_info answers.

Given the seeded ``law_info`` rows (``contract_type``, ``source``, ``content``),
:func:`extract_references` parses every law name wrapped in ``《...》`` out of the
markdown, deduplicates by canonical name, categorizes each, and records the
``(contract_type, source)`` pairs it appeared in.

This is the single extraction logic shared by:
- the ``/law-references`` web page (computes from ``law_info.content`` rows), and
- ``scripts/extract_legal_references.py`` (writes the committed
  ``docs/legal_references.md`` from the bundled markdown).

Pure (no DB, no I/O): callers feed in the items. Deterministic output (sorted
by category then name) so the generated doc is reproducible.
"""

from __future__ import annotations

import re
from typing import Iterable

# Law names in the surveys are consistently wrapped in 《...》.
_LAW_NAME_RE = re.compile(r"《([^》\n]+)》")

# Category display order (used for sorting + rendering).
CATEGORY_ORDER = (
    "core_law",
    "judicial_interpretation",
    "special_statute",
    "procedural",
    "other",
)

CATEGORY_ZH = {
    "core_law": "核心法律",
    "judicial_interpretation": "司法解释",
    "special_statute": "专项法规",
    "procedural": "程序法",
    "other": "其他",
}


def categorize(name: str) -> str:
    """Classify a law name into one of the five buckets.

    Heuristic, intentionally lenient - anything unmatched lands in ``other``
    rather than being dropped. Order matters: judicial interpretations are
    detected before generic 法-named statutes.
    """
    n = name
    if "最高人民法院" in n or "最高法" in n:
        return "judicial_interpretation"
    if any(k in n for k in ("公约", "条约", "协定")):
        return "special_statute"
    if any(k in n for k in ("条例", "办法", "细则", "规定", "规则", "目录", "清单")):
        return "special_statute"
    if any(k in n for k in ("民事诉讼法", "仲裁法", "行政诉讼法", "刑事诉讼法", "证据")):
        return "procedural"
    if n.endswith("法") or n.endswith("法典"):
        return "core_law"
    return "other"


def _canonical(name: str) -> str:
    """Normalize a law name for display (strip surrounding whitespace).

    Keeps the inner text intact - the display name IS the canonical name.
    """
    return name.strip()


def _dedup_key(name: str) -> str:
    """Normalization key used to merge the same law cited two ways.

    Strips the common ``中华人民共和国`` prefix so e.g. ``中华人民共和国专利法``
    and ``专利法`` collapse into one entry. The longest formal name seen is kept
    as the display name.
    """
    n = name.strip()
    if n.startswith("中华人民共和国"):
        n = n[len("中华人民共和国"):]
    return n


def extract_references(items: Iterable[dict]) -> list[dict]:
    """Aggregate the unique laws referenced across ``items``.

    Each item is ``{contract_type, source, content}`` (``zh_name`` optional,
    ignored here). Returns a list of::

        {
          "name": str,                 # canonical law name (no 《》)
          "category": str,             # one of CATEGORY_ORDER
          "category_zh": str,
          "contract_types": [str, ...],# sorted unique types it appeared in
          "sources": [str, ...],       # sorted unique sources
          "occurrences": int,          # total (type, source) pairs it appeared in
        }

    Sorted by (category order, name) for deterministic output.
    """
    # dedup_key -> {"name": longest display, "contract_types": set, "sources": set, "occurrences": int}
    agg: dict[str, dict] = {}

    for item in items:
        content = item.get("content") or ""
        ct = item.get("contract_type")
        src = item.get("source")
        if not content or ct is None or src is None:
            continue
        seen_here = set(_LAW_NAME_RE.findall(content))
        for raw in seen_here:
            name = _canonical(raw)
            if not name:
                continue
            key = _dedup_key(name)
            entry = agg.setdefault(
                key,
                {"name": name, "contract_types": set(), "sources": set(), "occurrences": 0},
            )
            # Keep the longest formal name as the display name.
            if len(name) > len(entry["name"]):
                entry["name"] = name
            entry["contract_types"].add(ct)
            entry["sources"].add(src)
            entry["occurrences"] += 1

    out: list[dict] = []
    for entry in agg.values():
        cat = categorize(entry["name"])
        out.append(
            {
                "name": entry["name"],
                "category": cat,
                "category_zh": CATEGORY_ZH[cat],
                "contract_types": sorted(entry["contract_types"]),
                "sources": sorted(entry["sources"]),
                "occurrences": entry["occurrences"],
            }
        )
    out.sort(key=lambda r: (CATEGORY_ORDER.index(r["category"]), r["name"]))
    return out
