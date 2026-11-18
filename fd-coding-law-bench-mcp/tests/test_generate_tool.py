"""Tests for ``contract_generate``.

Hermetic: the wrapped ``src.*`` functions are monkeypatched, so no DB, network,
LibreOffice, or template files are touched. These tests verify the tool's own
dispatch / param-mapping / ``current_tags`` logic.
"""

from __future__ import annotations

import pytest

# Mark all tests in this file as asyncio tests
pytestmark = pytest.mark.asyncio


def _skeleton_result(**over):
    base = {
        "docx_path": None,
        "pdf_path": "/tmp/sale.pdf",
        "body_text": "## 当事人\n甲方：{{party_a}}",
        "slots": ["party_a"],
        "instructions": [{"name": "party_a"}],
        "laws": [{"name": "民法典"}],
    }
    base.update(over)
    return base


def _assembled_result(**over):
    base = {
        "docx_path": None,
        "pdf_path": "/tmp/employment.pdf",
        "body_text": "## 当事人\n甲方：{{party_a}}",
        "slots": ["party_a"],
        "instructions": [],
        "law_refs": [{"name": "劳动合同法"}],
    }
    base.update(over)
    return base


async def test_known_type_uses_skeleton_path(monkeypatch):
    import src.contracts as contracts_mod

    calls = {}

    def fake_generate(contract_type, *, format="pdf", out_dir=None):
        calls.update(contract_type=contract_type, format=format, out_dir=out_dir)
        return _skeleton_result()

    monkeypatch.setattr(contracts_mod, "generate_contract", fake_generate)

    from fd_coding_law_bench_mcp.tools.generate import contract_generate

    res = await contract_generate("sale", format="pdf")
    assert calls == {"contract_type": "sale", "format": "pdf", "out_dir": None}
    assert res["pdf_path"] == "/tmp/sale.pdf"
    assert "laws" in res
    assert "current_tags" not in res


async def test_stance_routes_to_assembled(monkeypatch):
    import src.clauses.assemble as assemble_mod

    calls = {}

    def fake_assembled(
        contract_type,
        *,
        scenario=None,
        custom_clause_ids=None,
        stance=None,
        format="pdf",
        out_dir=None,
        db=None,
    ):
        calls.update(contract_type=contract_type, scenario=scenario, stance=stance, format=format)
        return _assembled_result()

    monkeypatch.setattr(assemble_mod, "generate_contract_assembled", fake_assembled)

    from fd_coding_law_bench_mcp.tools.generate import contract_generate

    res = await contract_generate("employment", stance="pro_a")
    assert calls["stance"] == "pro_a"
    assert calls["scenario"] is None
    assert "law_refs" in res


async def test_tags_scenario_routes_to_assembled_with_scenario(monkeypatch):
    import src.clauses.assemble as assemble_mod

    calls = {}

    def fake_assembled(
        contract_type, *, scenario=None, custom_clause_ids=None, stance=None,
        format="pdf", out_dir=None, db=None,
    ):
        calls.update(scenario=scenario, stance=stance)
        return _assembled_result()

    monkeypatch.setattr(assemble_mod, "generate_contract_assembled", fake_assembled)

    from fd_coding_law_bench_mcp.tools.generate import contract_generate

    await contract_generate("sale", tags={"scenario": "农产品买卖"})
    assert calls["scenario"] == "农产品买卖"
    assert calls["stance"] is None


async def test_tags_region_ignored(monkeypatch):
    # region/province are no longer recognized; with no stance/scenario the
    # tool falls back to the skeleton path (assemble never called).
    import src.contracts as contracts_mod
    import src.clauses.assemble as assemble_mod

    assembled = {"n": 0}

    def fake_assembled(*a, **k):
        assembled["n"] += 1
        return _assembled_result()

    monkeypatch.setattr(assemble_mod, "generate_contract_assembled", fake_assembled)
    monkeypatch.setattr(contracts_mod, "generate_contract", lambda *a, **k: _skeleton_result())

    from fd_coding_law_bench_mcp.tools.generate import contract_generate

    res = await contract_generate("sale", tags={"region": "广东"})
    assert assembled["n"] == 0  # region ignored -> skeleton path
    assert "laws" in res  # skeleton result marker


async def test_include_current_tags_returns_vocab_with_temp_dim(monkeypatch):
    import src.clauses.tags as tags_mod
    import src.contracts as contracts_mod

    # Skip the DB merge; load_vocab_from_db becomes a no-op so the live
    # TAG_VOCAB (incl. the temp dim registered below) is what gets snapshotted.
    monkeypatch.setattr(tags_mod, "load_vocab_from_db", lambda db=None: tags_mod.TAG_VOCAB)
    monkeypatch.setattr(contracts_mod, "generate_contract", lambda *a, **k: _skeleton_result())

    tags_mod.register_tag_dim(None, "vam_mechanism", values=["equity_adjust", "cash_compensation"])

    from fd_coding_law_bench_mcp.tools.generate import contract_generate

    res = await contract_generate("sale", include_current_tags=True)
    ct = res["current_tags"]
    for dim in ("stance", "strength", "risk", "mandatory"):
        assert dim in ct
    assert ct["vam_mechanism"] == ["equity_adjust", "cash_compensation"]


async def test_include_current_tags_false_omits_field(monkeypatch):
    import src.contracts as contracts_mod

    monkeypatch.setattr(contracts_mod, "generate_contract", lambda *a, **k: _skeleton_result())

    from fd_coding_law_bench_mcp.tools.generate import contract_generate

    res = await contract_generate("sale", include_current_tags=False)
    assert "current_tags" not in res


async def test_unknown_type_propagates(monkeypatch):
    import src.contracts as contracts_mod
    from src.eval.errors import NotFoundError

    def boom(contract_type, *, format="pdf", out_dir=None):
        raise NotFoundError(f"unknown contract type: {contract_type!r}")

    monkeypatch.setattr(contracts_mod, "generate_contract", boom)

    from fd_coding_law_bench_mcp.tools.generate import contract_generate

    with pytest.raises(NotFoundError):
        await contract_generate("not_a_real_type")


# --- redesign-tag-driven-assembly: override pass-through + coherence error ---

async def test_scenario_and_stance_both_passed_to_assembled(monkeypatch):
    import src.clauses.assemble as assemble_mod

    calls = {}

    def fake_assembled(contract_type, *, scenario=None, custom_clause_ids=None,
                       stance=None, format="pdf", out_dir=None, db=None):
        calls.update(scenario=scenario, stance=stance)
        return _assembled_result()

    monkeypatch.setattr(assemble_mod, "generate_contract_assembled", fake_assembled)

    from fd_coding_law_bench_mcp.tools.generate import contract_generate

    await contract_generate("sale", tags={"scenario": "家具买卖"}, stance="balanced")
    assert calls["scenario"] == "家具买卖"
    assert calls["stance"] == "balanced"


async def test_coherence_error_propagates(monkeypatch):
    """A coherence-gate failure surfaces to the client as a tool error."""
    import src.clauses.assemble as assemble_mod
    from src.clauses.coherence import CoherenceError

    def boom(contract_type, *, scenario=None, custom_clause_ids=None, stance=None,
             format="pdf", out_dir=None, db=None):
        raise CoherenceError("un-instructed slots: ['foo']")

    monkeypatch.setattr(assemble_mod, "generate_contract_assembled", boom)

    from fd_coding_law_bench_mcp.tools.generate import contract_generate

    with pytest.raises(CoherenceError):
        await contract_generate("sale", stance="balanced")


# --- add-contract-pipeline: custom_clause_ids + body_text ---

async def test_custom_clause_ids_forwarded_to_assembled(monkeypatch):
    import src.clauses.assemble as assemble_mod

    captured = {}

    def fake_assembled(contract_type, *, scenario=None, custom_clause_ids=None,
                       stance=None, format="pdf", out_dir=None, db=None):
        captured["custom_clause_ids"] = custom_clause_ids
        return _assembled_result()

    monkeypatch.setattr(assemble_mod, "generate_contract_assembled", fake_assembled)

    from fd_coding_law_bench_mcp.tools.generate import contract_generate

    await contract_generate("sale", stance="balanced", custom_clause_ids=[420, 421])
    assert captured["custom_clause_ids"] == [420, 421]


async def test_custom_clause_ids_none_default_unchanged(monkeypatch):
    import src.clauses.assemble as assemble_mod

    captured = {}

    def fake_assembled(contract_type, *, scenario=None, custom_clause_ids=None,
                       stance=None, format="pdf", out_dir=None, db=None):
        captured["custom_clause_ids"] = custom_clause_ids
        return _assembled_result()

    monkeypatch.setattr(assemble_mod, "generate_contract_assembled", fake_assembled)

    from fd_coding_law_bench_mcp.tools.generate import contract_generate

    await contract_generate("sale", stance="balanced")
    assert captured["custom_clause_ids"] is None  # default selection


async def test_body_text_returned_skeleton(monkeypatch):
    import src.contracts as contracts_mod

    monkeypatch.setattr(contracts_mod, "generate_contract", lambda *a, **k: _skeleton_result())

    from fd_coding_law_bench_mcp.tools.generate import contract_generate

    res = await contract_generate("sale", format="pdf")
    assert res["body_text"] == "## 当事人\n甲方：{{party_a}}"
