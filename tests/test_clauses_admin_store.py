"""Tests for the clause-admin store CRUD (create/update/delete/search + manual)."""

from __future__ import annotations

import pytest

from src.clauses.store import (
    create_clause,
    delete_auto_clauses,
    delete_clause,
    list_clauses,
    search_clauses,
    upsert_clause,
    update_clause,
)
from src.eval.errors import NotFoundError


def test_create_custom_clause_derives_and_marks_manual(seeded_db):
    cid = create_clause(
        {
            "contract_type": "sale",
            "category": "custom",
            "section": "附则",
            "body": "本合同一式{{n_copies}}份，依据《民法典》。",
            "province": None,
            "source_doc_title": "T",
        },
        db=seeded_db,
    )
    rows = list_clauses("sale", category="custom", db=seeded_db)
    c = [r for r in rows if r["id"] == cid][0]
    assert c["manual"] is True
    assert c["source_path"] is None
    assert c["level"] is None
    assert {s["name"] for s in c["slot_instructions"]} == {"n_copies"}
    assert any(r["name"] == "民法典" for r in c["law_refs"])


def test_update_rederives_and_marks_manual(seeded_db):
    cid = create_clause(
        {"contract_type": "sale", "category": "custom", "section": "附则",
         "body": "old {{x}}", "province": None},
        db=seeded_db,
    )
    old = [c for c in list_clauses("sale", db=seeded_db) if c["id"] == cid][0]
    upd = update_clause(
        cid,
        {"body": "甲方：{{party_a}}，依据《民法典》。", "section": "当事人", "category": "base"},
        db=seeded_db,
    )
    assert upd["manual"] is True
    assert upd["section"] == "当事人"
    assert upd["category"] == "base"
    assert upd["tags"].get("region") is None  # region dim retired; base tags carry only source
    assert upd["body_hash"] != old["body_hash"]
    assert {s["name"] for s in upd["slot_instructions"]} == {"party_a"}
    assert any(r["name"] == "民法典" for r in upd["law_refs"])


def test_update_unknown_raises(seeded_db):
    with pytest.raises(NotFoundError):
        update_clause(999999, {"body": "x", "section": "附则", "category": "custom"}, db=seeded_db)


def test_delete_clause(seeded_db):
    cid = create_clause(
        {"contract_type": "sale", "category": "custom", "section": "附则", "body": "to delete {{x}}"},
        db=seeded_db,
    )
    assert delete_clause(cid, db=seeded_db) == 1
    assert all(c["id"] != cid for c in list_clauses("sale", db=seeded_db))


def test_delete_unknown_raises(seeded_db):
    with pytest.raises(NotFoundError):
        delete_clause(999999, db=seeded_db)


def test_search_clauses_by_body(seeded_db):
    create_clause(
        {"contract_type": "sale", "category": "custom", "section": "违约责任",
         "body": "特殊违约金条款 {{penalty}}"},
        db=seeded_db,
    )
    hits = search_clauses("违约金", contract_type="sale", db=seeded_db)
    assert len(hits) >= 1
    assert all("违约金" in c["body"] for c in hits)


def test_delete_auto_preserves_manual(seeded_db):
    sp = "t/admin.docx"
    upsert_clause(
        {"contract_type": "sale", "category": "base", "section": "标的",
         "body": "auto {{subject}}", "slot_instructions": [], "law_refs": [],
         "province": None, "level": "national", "source_path": sp,
         "source_doc_title": "T", "body_hash": "a1", "manual": False},
        db=seeded_db,
    )
    upsert_clause(
        {"contract_type": "sale", "category": "base", "section": "当事人",
         "body": "manual {{party_a}}", "slot_instructions": [], "law_refs": [],
         "province": None, "level": "national", "source_path": sp,
         "source_doc_title": "T", "body_hash": "m1", "manual": True},
        db=seeded_db,
    )
    n = delete_auto_clauses(sp, db=seeded_db)
    assert n == 1  # only the auto clause deleted
    remaining = list_clauses("sale", db=seeded_db)
    assert len(remaining) == 1
    assert remaining[0]["body_hash"] == "m1"
    assert remaining[0]["manual"] is True
