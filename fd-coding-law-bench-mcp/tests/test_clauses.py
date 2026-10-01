"""Tests for the clause management tools.

Hermetic: ``src.clauses.store`` and ``src.clauses.tag_review`` are monkeypatched
(no DB). Verifies delegation, param-mapping, delete/review acks, that
``clause_update`` only forwards non-``None`` fields, and error propagation.
"""

from __future__ import annotations

import pytest

# Mark all tests in this file as asyncio tests
pytestmark = pytest.mark.asyncio


async def test_clause_list_delegates(monkeypatch):
    import src.clauses.store as store

    captured = {}

    def fake_list(contract_type, *, category=None, tags=None, q=None, db=None):
        captured.update(contract_type=contract_type, category=category, tags=tags, q=q)
        return [{"id": 1}]

    monkeypatch.setattr(store, "list_clauses", fake_list)

    from fd_coding_law_bench_mcp.tools.clauses import clause_list

    out = await clause_list("sale", category="custom", tags={"stance": "balanced"}, q="风险")
    assert out == [{"id": 1}]
    assert captured == {
        "contract_type": "sale",
        "category": "custom",
        "tags": {"stance": "balanced"},
        "q": "风险",
    }


async def test_clause_get_delegates(monkeypatch):
    import src.clauses.store as store

    monkeypatch.setattr(
        store, "get_custom_clause", lambda cid, db=None: {"id": cid} if cid else None
    )

    from fd_coding_law_bench_mcp.tools.clauses import clause_get

    assert (await clause_get(7))["id"] == 7
    assert await clause_get(0) is None


async def test_clause_update_passes_only_non_none_fields(monkeypatch):
    import src.clauses.store as store

    captured = {}

    def fake_update(clause_id, fields, db=None):
        captured.update(clause_id=clause_id, fields=fields)
        return {"id": clause_id, **fields}

    monkeypatch.setattr(store, "update_clause", fake_update)

    from fd_coding_law_bench_mcp.tools.clauses import clause_update

    out = await clause_update(7, body="新正文", tags={"stance": "balanced"})
    assert captured["clause_id"] == 7
    assert captured["fields"] == {"body": "新正文", "tags": {"stance": "balanced"}}
    assert out["id"] == 7


async def test_clause_update_no_fields_passes_empty(monkeypatch):
    import src.clauses.store as store

    seen = {}
    monkeypatch.setattr(
        store,
        "update_clause",
        lambda cid, fields, db=None: seen.update(fields=fields) or {"id": cid},
    )

    from fd_coding_law_bench_mcp.tools.clauses import clause_update

    out = await clause_update(7)
    assert seen["fields"] == {}
    assert out["id"] == 7


async def test_clause_delete_returns_ack_and_delegates(monkeypatch):
    import src.clauses.store as store

    deleted = []
    monkeypatch.setattr(store, "delete_clause", lambda cid, db=None: deleted.append(cid))

    from fd_coding_law_bench_mcp.tools.clauses import clause_delete

    out = await clause_delete(5)
    assert deleted == [5]
    assert out == {"deleted": True, "clause_id": 5}


async def test_clause_review_delegates_and_acks(monkeypatch):
    import src.clauses.tag_review as tr

    captured = {}

    def fake_bulk(clause_id, status, db=None):
        captured.update(clause_id=clause_id, status=status)
        return None

    monkeypatch.setattr(tr, "bulk_review", fake_bulk)

    from fd_coding_law_bench_mcp.tools.clauses import clause_review

    out = await clause_review(420, "rejected")
    assert captured == {"clause_id": 420, "status": "rejected"}
    assert out == {"reviewed": True, "clause_id": 420, "status": "rejected"}


async def test_clause_review_invalid_status_raises(monkeypatch):
    import src.clauses.tag_review as tr

    def boom(clause_id, status, db=None):
        raise ValueError(f"invalid status: {status!r}")

    monkeypatch.setattr(tr, "bulk_review", boom)

    from fd_coding_law_bench_mcp.tools.clauses import clause_review

    with pytest.raises(ValueError):
        await clause_review(1, "bogus")
