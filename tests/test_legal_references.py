"""Tests for the pure legal-references extractor and the reference-doc generator.

The extractor parses ``《...》`` law names out of law_info content, deduplicates
(canonicalizing the ``中华人民共和国`` prefix), categorizes, and tags each law
with the ``(contract_type, source)`` pairs it appeared in. The doc generator
must be deterministic so re-running produces an identical file.
"""

from __future__ import annotations

import sys
from pathlib import Path

from src.eval.legal_refs import (
    CATEGORY_ORDER,
    categorize,
    extract_references,
)

# Inject scripts/ onto sys.path so the generator module is importable.
_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from extract_legal_references import _render  # noqa: E402


ITEMS = [
    {
        "contract_type": "sale",
        "source": "doubao",
        "content": "依据《中华人民共和国民法典》及《最高人民法院关于审理买卖合同纠纷案件适用法律问题的解释》（法释〔2020〕17号）。",
    },
    {
        "contract_type": "sale",
        "source": "deepseek",
        "content": "依据《民法典》及《民事诉讼法》。",
    },
    {
        "contract_type": "loan",
        "source": "doubao",
        "content": "依据《中华人民共和国民法典》及《商业银行法》。",
    },
]


def test_categorize_buckets():
    assert categorize("中华人民共和国民法典") == "core_law"
    assert categorize("最高人民法院关于审理买卖合同纠纷案件适用法律问题的解释") == "judicial_interpretation"
    assert categorize("商业特许经营管理条例") == "special_statute"
    assert categorize("民事诉讼法") == "procedural"
    assert categorize("联合国国际货物销售合同公约") == "special_statute"


def test_extract_dedups_prefix_canonical():
    refs = extract_references(ITEMS)
    names = [r["name"] for r in refs]
    # 民法典 (bare) and 中华人民共和国民法典 merge into the longest formal name.
    assert "中华人民共和国民法典" in names
    assert "民法典" not in names
    # appears only once
    assert sum(1 for r in refs if r["name"] == "中华人民共和国民法典") == 1


def test_extract_tags_type_and_source():
    refs = extract_references(ITEMS)
    by_name = {r["name"]: r for r in refs}
    mc = by_name["中华人民共和国民法典"]
    # appeared in sale (doubao + deepseek) and loan (doubao)
    assert set(mc["contract_types"]) == {"sale", "loan"}
    assert set(mc["sources"]) == {"doubao", "deepseek"}


def test_extract_categorizes_and_sorts():
    refs = extract_references(ITEMS)
    cats = [r["category"] for r in refs]
    # sorted by CATEGORY_ORDER then name - core_law before judicial_interpretation
    order_idx = [CATEGORY_ORDER.index(c) for c in cats]
    assert order_idx == sorted(order_idx)
    assert "core_law" in cats
    assert "judicial_interpretation" in cats


def test_extract_skips_items_without_content():
    refs = extract_references([{"contract_type": "x", "source": "doubao", "content": ""}])
    assert refs == []


def test_doc_render_is_deterministic():
    refs = extract_references(ITEMS)
    a = _render(refs)
    b = _render(refs)
    assert a == b
    assert "# 法律法规索引" in a
    assert "中华人民共和国民法典" in a
