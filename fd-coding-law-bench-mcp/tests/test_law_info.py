"""Tests for the law-info & legal-references read tools.

Hermetic: ``src.eval.law_info`` and ``src.eval.legal_refs`` are monkeypatched
(no DB). Verifies delegation, error propagation, and the extract pipeline.
"""

from __future__ import annotations

import pytest

# Mark all tests in this file as asyncio tests
pytestmark = pytest.mark.asyncio


async def test_list_law_info_types_delegates(monkeypatch):
    import src.eval.law_info as li

    monkeypatch.setattr(
        li, "list_law_info_types",
        lambda: [{"key": "sale", "zh_name": "买卖合同", "sources": ["doubao", "deepseek"]}],
    )

    from fd_coding_law_bench_mcp.tools.law_info import law_types

    out = await law_types()
    assert out == [{"key": "sale", "zh_name": "买卖合同", "sources": ["doubao", "deepseek"]}]


async def test_get_law_info_unknown_raises(monkeypatch):
    import src.eval.law_info as li
    from src.eval.errors import NotFoundError

    def boom(contract_type):
        raise NotFoundError(f"law_info not found for contract type: {contract_type!r}")

    monkeypatch.setattr(li, "get_law_info", boom)

    from fd_coding_law_bench_mcp.tools.law_info import law_info

    with pytest.raises(NotFoundError):
        await law_info("not_a_type")


async def test_get_law_info_returns_both_sources(monkeypatch):
    import src.eval.law_info as li

    monkeypatch.setattr(
        li, "get_law_info",
        lambda contract_type: {"type": contract_type, "zh_name": "买卖合同",
                                "doubao": "# doubao survey", "deepseek": "# deepseek survey"},
    )

    from fd_coding_law_bench_mcp.tools.law_info import law_info

    out = await law_info("sale")
    assert out["type"] == "sale"
    assert out["doubao"] == "# doubao survey"
    assert out["deepseek"] == "# deepseek survey"


async def test_extract_legal_references_pipes_all_through_extractor(monkeypatch):
    import src.eval.law_info as li
    import src.eval.legal_refs as lr

    items = [{"contract_type": "sale", "source": "doubao", "content": "《民法典》"}]
    laws = [{"name": "民法典", "category": "core_law", "category_zh": "核心法律",
             "contract_types": ["sale"], "sources": ["doubao"], "occurrences": 1}]
    received = {}

    monkeypatch.setattr(li, "all_law_info", lambda: items)
    monkeypatch.setattr(lr, "extract_references",
                        lambda its: (received.setdefault("items", its), laws)[1])

    from fd_coding_law_bench_mcp.tools.law_info import law_references

    out = await law_references()
    assert out == laws
    assert received["items"] == items
