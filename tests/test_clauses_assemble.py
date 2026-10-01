"""Tests for clause-assembled contract generation (src/clauses/assemble.py)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from docx import Document

from src.clauses import generate_contract_assembled
from src.clauses.store import upsert_clause
from src.eval.errors import NotFoundError


def _soffice_available() -> bool:
    return shutil.which("soffice") is not None or shutil.which("libreoffice") is not None


def _seed(seeded_db) -> None:
    upsert_clause(
        {
            "contract_type": "sale", "category": "base", "section": "当事人",
            "body": "甲方：{{party_a}}（base-marker）",
            "slot_instructions": [{"name": "party_a", "label": "甲方", "description": "d", "example": "x", "required": True}],
            "law_refs": [{"name": "中华人民共和国民法典", "category": "core_law", "category_zh": "核心法律"}],
            "tags": {}, "level": "national", "source_path": "t/base.docx",
            "source_doc_title": "T", "body_hash": "b1",
        },
        db=seeded_db,
    )
    upsert_clause(
        {
            "contract_type": "sale", "category": "tagged", "section": "违约责任",
            "body": "违约金{{penalty}}（jinlin-marker），另有 {{property_name}}",
            "slot_instructions": [
                {"name": "penalty", "label": "违约金", "description": "d", "example": "10%", "required": False},
                {"name": "property_name", "label": "标的名称", "description": "d", "example": "x", "required": True},
            ],
            "law_refs": [], "tags": {"scenario": "农产品买卖"}, "level": "local", "source_path": "t/jl.docx",
            "source_doc_title": "T", "body_hash": "t1",
        },
        db=seeded_db,
    )


def _docx_text(path: str) -> str:
    d = Document(path)
    return "\n".join(p.text for p in d.paragraphs)


def test_assemble_base_only(seeded_db):
    _seed(seeded_db)
    r = generate_contract_assembled("sale", format="docx", db=seeded_db)
    assert Path(r["docx_path"]).exists()
    txt = _docx_text(r["docx_path"])
    assert "base-marker" in txt
    # slot kept fillable, rendered to its per-type Chinese name ({{甲方名称}})
    assert "{{甲方名称}}" in txt
    # canonical slot instructions present (Chinese-rendered) + clause-declared
    # slot absent (no tagged selected)
    names = {i["name"] for i in r["instructions"]}
    assert "甲方名称" in names  # canonical, Chinese-rendered


def test_assemble_with_scenario_includes_tagged(seeded_db):
    _seed(seeded_db)
    r = generate_contract_assembled("sale", scenario="农产品买卖", format="docx", db=seeded_db)
    txt = _docx_text(r["docx_path"])
    assert "base-marker" in txt
    assert "jinlin-marker" in txt
    # clause-declared slots surface in instructions, rendered to Chinese where a
    # concept mapping exists (penalty -> 违约金); property_name has no mapping so
    # it stays Latin.
    names = {i["name"] for i in r["instructions"]}
    assert "property_name" in names
    assert "违约金" in names
    # law_refs deduped union
    assert any(ref["name"] == "中华人民共和国民法典" for ref in r["law_refs"])


def test_assemble_with_custom(seeded_db):
    _seed(seeded_db)
    cid = upsert_clause(
        {
            "contract_type": "sale", "category": "custom", "section": "附则",
            "body": "custom-marker {{sign_location}}",
            "slot_instructions": [{"name": "sign_location", "label": "签署地点", "description": "d", "example": "北京", "required": False}],
            "law_refs": [], "level": None, "source_path": None,
            "source_doc_title": None, "body_hash": "c1",
        },
        db=seeded_db,
    )
    from src.clauses.tag_review import bulk_review
    bulk_review(cid, "approved", db=seeded_db)
    r = generate_contract_assembled(
        "sale", custom_clause_ids=[cid], format="docx", db=seeded_db
    )
    txt = _docx_text(r["docx_path"])
    assert "custom-marker" in txt


def test_assemble_section_ordering(seeded_db):
    _seed(seeded_db)
    r = generate_contract_assembled("sale", scenario="农产品买卖", format="docx", db=seeded_db)
    txt = _docx_text(r["docx_path"])
    # 当事人 (base) before 违约责任 (tagged)
    assert txt.index("当事人") < txt.index("违约责任")


def test_assemble_unknown_type_raises(seeded_db):
    with pytest.raises(NotFoundError):
        generate_contract_assembled("does_not_exist", format="docx", db=seeded_db)


def test_assemble_bad_format(seeded_db):
    with pytest.raises(ValueError):
        generate_contract_assembled("sale", format="rtf", db=seeded_db)


@pytest.mark.skipif(not _soffice_available(), reason="soffice/PDF backend unavailable")
def test_assemble_pdf(seeded_db):
    _seed(seeded_db)
    r = generate_contract_assembled("sale", scenario="农产品买卖", format="pdf", db=seeded_db)
    assert r["pdf_path"] and Path(r["pdf_path"]).exists()
    assert r["docx_path"] is None


# --- override semantics (redesign-tag-driven-assembly) ---

def _up(seeded_db, **kw):
    kw.setdefault("contract_type", "sale")
    kw.setdefault("slot_instructions", [])
    kw.setdefault("law_refs", [])
    kw.setdefault("source_doc_title", "T")
    kw.setdefault("source_path", "t/x.docx")
    return upsert_clause(kw, db=seeded_db)


def test_override_tagged_replaces_base_same_section(seeded_db):
    _up(seeded_db, category="base", section="当事人", body="base-party {{party_a}}", body_hash="b1")
    _up(seeded_db, category="tagged", section="当事人", body="tagged-party {{party_a}}",
        tags={"scenario": "家具买卖"}, body_hash="t1")
    r = generate_contract_assembled("sale", scenario="家具买卖", format="docx", db=seeded_db)
    txt = _docx_text(r["docx_path"])
    assert "tagged-party" in txt
    assert "base-party" not in txt  # override, not concat
    assert txt.count("当事人") == 1


def test_custom_overrides_tagged_and_base(seeded_db):
    _up(seeded_db, category="base", section="违约责任", body="base-pen {{penalty}}", body_hash="b1")
    _up(seeded_db, category="tagged", section="违约责任", body="tagged-pen {{penalty}}",
        tags={"scenario": "家具买卖"}, body_hash="t1")
    cid = _up(seeded_db, category="custom", section="违约责任", body="custom-pen {{penalty}}",
               tags={"stance": "pro_a"}, source_path=None, body_hash="c1")
    from src.clauses.tag_review import bulk_review
    bulk_review(cid, "approved", db=seeded_db)
    r = generate_contract_assembled("sale", scenario="家具买卖", stance="pro_a", format="docx", db=seeded_db)
    txt = _docx_text(r["docx_path"])
    assert "custom-pen" in txt
    assert "base-pen" not in txt and "tagged-pen" not in txt


def test_base_fallback_when_no_override(seeded_db):
    _up(seeded_db, category="base", section="争议解决", body="base-juris {{jurisdiction}}", body_hash="b1")
    r = generate_contract_assembled("sale", format="docx", db=seeded_db)
    assert "base-juris" in _docx_text(r["docx_path"])


def test_section_extension_placed_before_fujie(seeded_db):
    _up(seeded_db, category="base", section="当事人", body="base {{party_a}}", body_hash="b1")
    _up(seeded_db, category="base", section="附则", body="fujie-clause", body_hash="b2")
    _up(seeded_db, category="tagged", section="质量检验", body="qc-clause {{subject}}",
        tags={"scenario": "农产品买卖"}, body_hash="t1")
    r = generate_contract_assembled("sale", scenario="农产品买卖", format="docx", db=seeded_db)
    txt = _docx_text(r["docx_path"])
    assert "质量检验" in txt and "qc-clause" in txt
    assert txt.index("质量检验") < txt.index("附则")


def test_within_source_tiebreak_prefers_manual(seeded_db):
    _up(seeded_db, category="tagged", section="合同标的", body="auto-marker {{subject}}",
        tags={"scenario": "家具买卖"}, body_hash="t1", manual=False)
    _up(seeded_db, category="tagged", section="合同标的", body="manual-marker {{subject}}",
        tags={"scenario": "家具买卖"}, body_hash="t2", manual=True)
    r = generate_contract_assembled("sale", scenario="家具买卖", format="docx", db=seeded_db)
    txt = _docx_text(r["docx_path"])
    assert "manual-marker" in txt and "auto-marker" not in txt
    assert "合同标的" in r["diagnostics"]["heuristic_sections"]
