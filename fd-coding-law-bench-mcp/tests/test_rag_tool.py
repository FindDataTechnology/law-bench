"""Tests for ``search_clauses``.

Hermetic: ``src.search.query.search`` is monkeypatched. Verifies chunk mapping
and graceful degradation to ``[]`` on backend failure.
"""

from __future__ import annotations

import pytest

# Mark all tests in this file as asyncio tests
pytestmark = pytest.mark.asyncio


async def test_rag_returns_chunks(monkeypatch):
    import src.search.query as query_mod

    monkeypatch.setattr(
        query_mod,
        "search",
        lambda query, top_k=5: [{"text": "c1", "source_path": "a.md", "score": 0.9}],
    )

    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    out = await search_clauses("试用期期限", top_k=3)
    assert out == [{"text": "c1", "source_path": "a.md", "score": 0.9}]


async def test_rag_degrades_to_empty_on_failure(monkeypatch):
    import src.search.query as query_mod

    def boom(query, top_k=5):
        raise RuntimeError("ES unreachable")

    monkeypatch.setattr(query_mod, "search", boom)

    from fd_coding_law_bench_mcp.tools.rag import search_clauses

    assert await search_clauses("anything") == []
