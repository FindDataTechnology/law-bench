"""Tests for the stored-artifact MCP tools (``contract_generate_stored``,
``contract_download``).

Hermetic: the wrapped ``src.contracts.artifacts`` functions are monkeypatched,
so no DB, MinIO, or file generation is touched. These verify the tool's own
param-mapping (``tags`` -> ``stance``/``scenario``) and the response shaping
(download URLs, ``None`` for a missing artifact).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


def _stored_result(**over):
    base = {
        "artifact_id": 7,
        "docx_url": "/api/contracts/artifacts/7/download?format=docx",
        "pdf_url": None,
        "body_text": "## 当事人\n甲方：{{party_a}}",
        "slots": ["party_a"],
        "reused": False,
    }
    base.update(over)
    return base


def _all_result(**over):
    base = {
        "contract_type": "sale",
        "format": "docx",
        "artifacts": [
            {"artifact_id": 7, "scenario": None, "stance": None, "docx_url": "/api/contracts/artifacts/7/download?format=docx", "pdf_url": None, "reused": False},
            {"artifact_id": 8, "scenario": "生鲜乳购销", "stance": None, "docx_url": "/api/contracts/artifacts/8/download?format=docx", "pdf_url": None, "reused": False},
        ],
        "count": 2,
        "new": 2,
        "reused": 0,
        "failed": 0,
        "failures": [],
    }
    base.update(over)
    return base


async def test_generate_stored_by_type_all_combos(monkeypatch):
    """No tags -> generate_all_stored (all scenario x stance x base combos)."""
    import src.contracts.artifacts as arts

    calls = {}

    def fake_all(contract_type, *, format="docx"):
        calls.update(contract_type=contract_type, format=format)
        return _all_result()

    monkeypatch.setattr(arts, "generate_all_stored", fake_all)

    from fd_coding_law_bench_mcp.tools.artifacts import contract_generate_stored

    res = await contract_generate_stored("sale", format="docx")
    assert calls == {"contract_type": "sale", "format": "docx"}
    assert res["count"] == 2
    assert res["artifacts"][0]["docx_url"].endswith("/download?format=docx")


async def test_generate_stored_extracts_scenario_stance_from_tags(monkeypatch):
    import src.contracts.artifacts as arts

    calls = {}

    def fake_generate(contract_type, *, scenario=None, stance=None, custom_clause_ids=None, format="docx"):
        calls.update(scenario=scenario, stance=stance)
        return _stored_result()

    monkeypatch.setattr(arts, "generate_stored", fake_generate)

    from fd_coding_law_bench_mcp.tools.artifacts import contract_generate_stored

    await contract_generate_stored(
        "sale", tags={"stance": "pro_a", "scenario": "生鲜乳购销"}
    )
    assert calls["stance"] == "pro_a"
    assert calls["scenario"] == "生鲜乳购销"


async def test_generate_stored_explicit_stance_overrides_tags(monkeypatch):
    import src.contracts.artifacts as arts

    calls = {}

    def fake_generate(contract_type, *, scenario=None, stance=None, custom_clause_ids=None, format="docx"):
        calls.update(stance=stance)
        return _stored_result()

    monkeypatch.setattr(arts, "generate_stored", fake_generate)

    from fd_coding_law_bench_mcp.tools.artifacts import contract_generate_stored

    await contract_generate_stored("sale", tags={"stance": "pro_b"}, stance="pro_a")
    assert calls["stance"] == "pro_a"  # explicit stance wins


async def test_download_returns_urls(monkeypatch):
    import src.contracts.artifacts as arts

    row = {
        "id": 7,
        "contract_type": "sale",
        "scenario": "生鲜乳购销",
        "stance": "pro_a",
        "body_text": "body",
        "slots": ["party_a"],
        "docx_key": "artifacts/sale/7.docx",
        "pdf_key": "artifacts/sale/7.pdf",
        "created_at": "2026-01-01",
    }
    monkeypatch.setattr(arts, "get_artifact", lambda aid, db=None: row if aid == 7 else None)

    from fd_coding_law_bench_mcp.tools.artifacts import contract_download

    res = await contract_download(7)
    assert res["artifact_id"] == 7
    assert res["download_urls"]["docx"].endswith("/7/download?format=docx")
    assert res["download_urls"]["pdf"].endswith("/7/download?format=pdf")
    # request a specific format -> top-level download_url
    res2 = await contract_download(7, format="pdf")
    assert res2["download_url"].endswith("/7/download?format=pdf")


async def test_download_missing_artifact_returns_none(monkeypatch):
    import src.contracts.artifacts as arts

    monkeypatch.setattr(arts, "get_artifact", lambda aid, db=None: None)

    from fd_coding_law_bench_mcp.tools.artifacts import contract_download

    res = await contract_download(999999)
    assert res is None
