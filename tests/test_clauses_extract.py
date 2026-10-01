"""Tests for the extraction pipeline (src/clauses/extract.py).

Hermetic: the LLM call is stubbed; the cache is neutralized.
"""

from __future__ import annotations

import json

import pytest

from src.clauses import extract


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch):
    monkeypatch.setattr(extract, "save_cache", lambda *a, **k: None)
    monkeypatch.setattr(extract, "load_cached", lambda *a, **k: None)


def _raw(**kw) -> dict:
    base = {
        "contract_type": "property_service",
        "source_doc_title": "测试合同",
        "province": None,
        "level": "national",
        "clauses": [
            {
                "section": "当事人",
                "body": "甲方：{{party_a}}，依据《中华人民共和国民法典》。",
                "slot_instructions": [
                    {"name": "party_a", "label": "甲方", "description": "d", "example": "x", "required": True}
                ],
            }
        ],
    }
    base.update(kw)
    return base


def test_post_process_national_is_base():
    rec = extract._post_process(_raw(), "test/doc.docx")
    c = rec["clauses"][0]
    assert c["category"] == "base"
    assert c["level"] == "national"
    assert c["tags"] == {"source": "base"}  # no region (dropped); no scenario in raw
    assert c["contract_type"] == "property_service"


def test_post_process_local_is_tagged():
    rec = extract._post_process(_raw(province="吉林", level="local"), "test/doc.docx")
    c = rec["clauses"][0]
    assert c["category"] == "tagged"
    assert c["level"] == "local"
    assert c["tags"] == {"source": "tagged"}  # region no longer set; province is record-level
    assert rec["province"] == "吉林"


def test_post_process_scenario_from_tags():
    raw = _raw(province="吉林", level="local")
    raw["clauses"][0]["tags"] = {"scenario": "农产品买卖", "stance": "pro_a"}
    rec = extract._post_process(raw, "test/doc.docx")
    c = rec["clauses"][0]
    assert c["tags"]["scenario"] == "农产品买卖"
    assert c["tags"]["stance"] == "pro_a"
    # auto-tagged dims (incl. scenario) enter tag_review as pending
    assert c["tag_review"]["scenario"] == "pending"
    assert c["tag_review"]["stance"] == "pending"


def test_post_process_unknown_type_normalized():
    rec = extract._post_process(_raw(contract_type="bogus_type"), "test/doc.docx")
    assert rec["contract_type"] == "unknown"
    assert rec["clauses"][0]["contract_type"] == "unknown"


def test_post_process_default_level_from_province():
    rec = extract._post_process(_raw(province="云南", level=None), "test/doc.docx")
    assert rec["level"] == "local"
    assert rec["clauses"][0]["category"] == "tagged"


def test_normalize_slot_instructions_adds_missing():
    body = "甲方：{{party_a}}，标的：{{subject}}"
    out = extract._normalize_slot_instructions(
        body,
        [{"name": "party_a", "label": "甲方", "description": "d", "example": "x", "required": True}],
    )
    names = {i["name"] for i in out}
    assert names == {"party_a", "subject"}
    # stubbed instruction for the missing slot
    subj = [i for i in out if i["name"] == "subject"][0]
    assert subj["description"] == ""


def test_normalize_slot_instructions_drops_extra():
    body = "甲方：{{party_a}}"
    out = extract._normalize_slot_instructions(
        body,
        [
            {"name": "party_a", "label": "甲方", "description": "d", "example": "x", "required": True},
            {"name": "ghost", "label": "g", "description": "", "example": "", "required": False},
        ],
    )
    assert [i["name"] for i in out] == ["party_a"]


def test_law_refs_from_body_categorizes():
    body = "依据《中华人民共和国民法典》及《吉林省物业管理条例》。"
    refs = extract._law_refs_from_body(body)
    names = {r["name"] for r in refs}
    assert "中华人民共和国民法典" in names
    assert "吉林省物业管理条例" in names
    # core_law vs special_statute
    cats = {r["name"]: r["category"] for r in refs}
    assert cats["中华人民共和国民法典"] == "core_law"
    assert cats["吉林省物业管理条例"] == "special_statute"


def test_extract_document_stubbed(monkeypatch):
    canned = _raw(province="吉林", level="local")
    monkeypatch.setattr(extract, "_call_llm", lambda prompt: json.dumps(canned))
    rec = extract.extract_document(
        {"source_path": "test/jl.docx", "ext": ".docx", "text": "some contract text"},
        use_cache=False,
    )
    assert rec["contract_type"] == "property_service"
    assert rec["province"] == "吉林"
    assert rec["level"] == "local"
    c = rec["clauses"][0]
    assert c["category"] == "tagged"
    assert c["body_hash"]
    assert c["source_path"] == "test/jl.docx"
    assert {i["name"] for i in c["slot_instructions"]} == {"party_a"}
    assert any(r["name"] == "中华人民共和国民法典" for r in c["law_refs"])


def test_extract_document_empty_text_no_llm(monkeypatch):
    called = {"n": 0}

    def _boom(prompt):
        called["n"] += 1
        raise AssertionError("LLM should not be called for empty text")

    monkeypatch.setattr(extract, "_call_llm", _boom)
    rec = extract.extract_document(
        {"source_path": "test/empty.docx", "ext": ".docx", "text": ""},
        use_cache=False,
    )
    assert rec["clauses"] == []
    assert called["n"] == 0
