"""Tests for the rubric & criterion management tools.

Hermetic: ``src.eval.rubric_crud`` is monkeypatched (no DB). Verifies delegation,
param-mapping, delete acks, and error propagation (incl. harbor read-only).
"""

from __future__ import annotations

import pytest

# Mark all tests in this file as asyncio tests
pytestmark = pytest.mark.asyncio


def _detail(**over):
    base = {
        "id": 1,
        "name": "contract_sale_v1",
        "context": "contract",
        "source": "local",
        "source_path": None,
        "description": "d",
        "created_at": "2026-01-01T00:00:00+00:00",
        "is_harbor": False,
        "criterion_count": 2,
        "criteria": [
            {"id": 10, "name": "c1", "description": "d", "guidance": "g", "ordinal": 0},
            {"id": 11, "name": "c2", "description": "d", "guidance": "g", "ordinal": 1},
        ],
    }
    base.update(over)
    return base


async def test_get_rubric_returns_detail(monkeypatch):
    import src.eval.rubric_crud as rc

    monkeypatch.setattr(rc, "get_rubric_detail", lambda name: _detail(name=name))

    from fd_coding_law_bench_mcp.tools.rubrics import rubric_get

    out = await rubric_get("contract_sale_v1")
    assert out["name"] == "contract_sale_v1"
    assert out["is_harbor"] is False
    assert [c["name"] for c in out["criteria"]] == ["c1", "c2"]


async def test_create_rubric_round_trips(monkeypatch):
    import src.eval.rubric_crud as rc

    calls = {}

    def fake_create(name, context, description=None, criteria=None):
        calls.update(name=name, context=context, description=description, criteria=criteria)
        return _detail(name=name, context=context)

    monkeypatch.setattr(rc, "create_rubric", fake_create)

    from fd_coding_law_bench_mcp.tools.rubrics import rubric_create

    out = await rubric_create(
        "r", "contract", description="d",
        criteria=[{"name": "c1", "description": "d", "guidance": "g"}],
    )
    assert calls["name"] == "r"
    assert calls["criteria"][0]["name"] == "c1"
    assert out["name"] == "r"


async def test_update_rubric_on_harbor_raises(monkeypatch):
    import src.eval.rubric_crud as rc
    from src.eval.errors import HarborReadOnlyError

    def boom(rubric_id, name, context, description=None):
        raise HarborReadOnlyError("harbor read-only")

    monkeypatch.setattr(rc, "update_rubric", boom)

    from fd_coding_law_bench_mcp.tools.rubrics import rubric_update

    with pytest.raises(HarborReadOnlyError):
        await rubric_update(7, "n", "contract")


async def test_delete_rubric_returns_ack_and_delegates(monkeypatch):
    import src.eval.rubric_crud as rc

    deleted = []
    monkeypatch.setattr(rc, "delete_rubric", lambda rubric_id: deleted.append(rubric_id))

    from fd_coding_law_bench_mcp.tools.rubrics import rubric_delete

    out = await rubric_delete(5)
    assert deleted == [5]
    assert out == {"deleted": True, "rubric_id": 5}


async def test_reorder_criteria_mismatched_raises(monkeypatch):
    import src.eval.rubric_crud as rc
    from src.eval.errors import ValidationError

    def boom(rubric_id, ordered_criterion_ids):
        raise ValidationError("reorder list mismatch")

    monkeypatch.setattr(rc, "reorder_criteria", boom)

    from fd_coding_law_bench_mcp.tools.rubrics import criterion_reorder

    with pytest.raises(ValidationError):
        await criterion_reorder(1, [1, 2])


async def test_add_criterion_delegates(monkeypatch):
    import src.eval.rubric_crud as rc

    monkeypatch.setattr(
        rc, "add_criterion",
        lambda rubric_id, name, description, guidance: {"id": 12, "rubric_id": rubric_id, "name": name},
    )

    from fd_coding_law_bench_mcp.tools.rubrics import criterion_add

    out = await criterion_add(1, "c3", "desc", "guidance")
    assert out == {"id": 12, "rubric_id": 1, "name": "c3"}
