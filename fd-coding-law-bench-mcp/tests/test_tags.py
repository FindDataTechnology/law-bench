"""Tests for the read-only tag tools (``tag_vocab_list`` / ``tag_validate``).

Hermetic: ``src.clauses.tags`` is monkeypatched (no DB). Verifies delegation to
``tag_vocab_for_type`` / ``validate_tags`` and the load-before-read refresh that
mirrors ``contract_generate``'s ``include_current_tags`` path.
"""

from __future__ import annotations

import pytest

# Mark all tests in this file as asyncio tests
pytestmark = pytest.mark.asyncio


async def test_tag_vocab_list_delegates_and_loads_first(monkeypatch):
    import src.clauses.tags as tags_mod

    order = []

    def fake_load(db=None):
        order.append("load")
        return tags_mod.TAG_VOCAB

    def fake_vocab(contract_type):
        order.append("vocab")
        return {"stance": ["pro_a", "pro_b", "balanced"]}

    monkeypatch.setattr(tags_mod, "load_vocab_from_db", fake_load)
    monkeypatch.setattr(tags_mod, "tag_vocab_for_type", fake_vocab)

    from fd_coding_law_bench_mcp.tools.tags import tag_vocab_list

    out = await tag_vocab_list("sale")
    assert out == {"stance": ["pro_a", "pro_b", "balanced"]}
    assert order == ["load", "vocab"]  # load refresh happens before the read


async def test_tag_vocab_list_universal_only_when_no_type(monkeypatch):
    import src.clauses.tags as tags_mod

    monkeypatch.setattr(tags_mod, "load_vocab_from_db", lambda db=None: tags_mod.TAG_VOCAB)
    monkeypatch.setattr(
        tags_mod, "tag_vocab_for_type",
        lambda ct: {"stance": ["pro_a", "pro_b", "balanced"],
                    "strength": ["strong", "standard", "mild"]},
    )

    from fd_coding_law_bench_mcp.tools.tags import tag_vocab_list

    out = await tag_vocab_list(None)
    assert "stance" in out and "strength" in out


async def test_tag_validate_returns_cleaned(monkeypatch):
    import src.clauses.tags as tags_mod

    cleaned = {"stance": "pro_a"}

    monkeypatch.setattr(tags_mod, "load_vocab_from_db", lambda db=None: tags_mod.TAG_VOCAB)
    monkeypatch.setattr(tags_mod, "validate_tags", lambda tags, contract_type=None: cleaned)

    from fd_coding_law_bench_mcp.tools.tags import tag_validate

    out = await tag_validate({"stance": "pro_a", "mood": "happy"}, contract_type="sale")
    assert out == {"stance": "pro_a"}


async def test_tag_validate_invalid_value_propagates(monkeypatch):
    import src.clauses.tags as tags_mod

    def boom(tags, contract_type=None):
        raise ValueError("invalid tag value: stance='pro_A'; allowed: ['pro_a', 'pro_b', 'balanced']")

    monkeypatch.setattr(tags_mod, "load_vocab_from_db", lambda db=None: tags_mod.TAG_VOCAB)
    monkeypatch.setattr(tags_mod, "validate_tags", boom)

    from fd_coding_law_bench_mcp.tools.tags import tag_validate

    with pytest.raises(ValueError):
        await tag_validate({"stance": "pro_A"})
