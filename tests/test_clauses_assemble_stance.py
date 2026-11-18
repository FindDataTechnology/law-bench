"""Tests for the assembly stance filter on custom clauses."""

from __future__ import annotations

import hashlib

import pytest

from src.clauses import generate_contract_assembled
from src.clauses.assemble import _select_clauses
from src.clauses.store import create_clause, upsert_clause
from src.eval.errors import NotFoundError


def _base(d: dict) -> dict:
    body = d["body"]
    d.setdefault("body_hash", hashlib.md5(body.encode("utf-8")).hexdigest())
    d.setdefault("slot_instructions", [])
    d.setdefault("law_refs", [])
    d.setdefault("province", None)
    d.setdefault("level", "national")
    d.setdefault("source_doc_title", "T")
    return d


def test_stance_filter_selects_only_matching_custom(seeded_db):
    from src.clauses.tag_review import bulk_review

    cid1 = create_clause({"contract_type": "sale", "category": "custom", "section": "违约责任",
                   "body": "偏甲违约金 {{a}}", "tags": {"stance": "pro_a"}}, db=seeded_db)
    cid2 = create_clause({"contract_type": "sale", "category": "custom", "section": "违约责任",
                   "body": "偏乙违约金 {{b}}", "tags": {"stance": "pro_b"}}, db=seeded_db)
    bulk_review(cid1, "approved", db=seeded_db)
    bulk_review(cid2, "approved", db=seeded_db)
    selected, _, _ = _select_clauses("sale", None, None, stance="pro_a", db=seeded_db)
    bodies = [c["body"] for c in selected]
    assert any("偏甲" in b for b in bodies)
    assert not any("偏乙" in b for b in bodies)


def test_stance_none_with_no_custom_returns_empty_custom(seeded_db):
    create_clause({"contract_type": "sale", "category": "custom", "section": "违约责任",
                   "body": "偏甲 {{a}}", "tags": {"stance": "pro_a"}}, db=seeded_db)
    # no stance, no custom ids -> custom selection empty (base/tagged only)
    selected, _, _ = _select_clauses("sale", None, None, stance=None, db=seeded_db)
    assert all(c["category"] != "custom" for c in selected)


def test_stance_does_not_affect_base(seeded_db):
    upsert_clause(_base({
        "contract_type": "sale", "category": "base", "section": "当事人",
        "body": "甲方 {{party_a}}", "source_path": "test://base",
    }), db=seeded_db)
    create_clause({"contract_type": "sale", "category": "custom", "section": "违约责任",
                   "body": "偏乙 {{b}}", "tags": {"stance": "pro_b"}}, db=seeded_db)
    selected, _, _ = _select_clauses("sale", None, None, stance="pro_a", db=seeded_db)
    # base clause is present regardless of stance
    assert any(c["category"] == "base" for c in selected)
    # pro_b custom excluded by the pro_a stance filter
    assert not any("偏乙" in c["body"] for c in selected)


def test_unknown_type_still_raises_with_stance(seeded_db):
    with pytest.raises(NotFoundError):
        generate_contract_assembled("does_not_exist", stance="pro_a", format="docx", db=seeded_db)
