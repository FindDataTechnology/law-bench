"""Tests for the prompt management tools.

Hermetic: ``src.eval.prompt_crud`` is monkeypatched (no DB). Verifies the
list/get shape, create+get round-trip, and error propagation.
"""

from __future__ import annotations

import pytest

# Mark all tests in this file as asyncio tests
pytestmark = pytest.mark.asyncio


def _row(**over):
    base = {
        "id": 1,
        "name": "draft_sale",
        "contract_type": "sale",
        "purpose": "draft a sale contract",
        "source": "local",
        "prompt_type": "baseline",
        "description": "d",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    base.update(over)
    return base


def _record(**over):
    base = _row()
    base["content"] = "You are a contract drafter..."
    base.update(over)
    return base


async def test_list_prompts_omits_content(monkeypatch):
    import src.eval.prompt_crud as pc

    monkeypatch.setattr(pc, "list_prompts", lambda: [_row()])

    from fd_coding_law_bench_mcp.tools.prompts import prompt_list

    rows = await prompt_list()
    assert len(rows) == 1
    assert rows[0]["name"] == "draft_sale"
    assert "content" not in rows[0]


async def test_get_prompt_returns_content(monkeypatch):
    import src.eval.prompt_crud as pc

    monkeypatch.setattr(pc, "get_prompt", lambda name: _record(name=name))

    from fd_coding_law_bench_mcp.tools.prompts import prompt_get

    out = await prompt_get("draft_sale")
    assert out["content"] == "You are a contract drafter..."
    assert out["name"] == "draft_sale"


async def test_create_then_get_round_trips(monkeypatch):
    import src.eval.prompt_crud as pc

    store = {}

    def fake_create(name, contract_type, purpose, content, description=None, prompt_type=None):
        rec = _record(name=name, contract_type=contract_type, purpose=purpose, content=content,
                      description=description, prompt_type=prompt_type, id=42)
        store[name] = rec
        return rec

    monkeypatch.setattr(pc, "create_prompt", fake_create)
    monkeypatch.setattr(pc, "get_prompt", lambda name: store[name])

    from fd_coding_law_bench_mcp.tools.prompts import prompt_create, prompt_get

    created = await prompt_create(
        "draft_lease", "lease", "draft a lease", "You draft leases...",
        description="lease drafter", prompt_type="baseline",
    )
    assert created["id"] == 42
    got = await prompt_get("draft_lease")
    assert got["content"] == "You draft leases..."
    assert got["contract_type"] == "lease"


async def test_delete_prompt_unknown_raises(monkeypatch):
    import src.eval.prompt_crud as pc
    from src.eval.errors import NotFoundError

    def boom(prompt_id):
        raise NotFoundError(f"Prompt not found: id={prompt_id}")

    monkeypatch.setattr(pc, "delete_prompt", boom)

    from fd_coding_law_bench_mcp.tools.prompts import prompt_delete

    with pytest.raises(NotFoundError):
        await prompt_delete(999)


async def test_delete_prompt_returns_ack(monkeypatch):
    import src.eval.prompt_crud as pc

    deleted = []
    monkeypatch.setattr(pc, "delete_prompt", lambda prompt_id: deleted.append(prompt_id))

    from fd_coding_law_bench_mcp.tools.prompts import prompt_delete

    out = await prompt_delete(7)
    assert deleted == [7]
    assert out == {"deleted": True, "prompt_id": 7}
