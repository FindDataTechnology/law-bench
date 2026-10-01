"""Tests for the clauses table CRUD (src/clauses/store.py)."""

from __future__ import annotations

import pytest

from src.clauses.store import (
    count_clauses,
    counts_by_type,
    delete_clauses,
    list_clauses,
    upsert_clause,
    upsert_clauses,
)


def _clause(**kw) -> dict:
    base = {
        "contract_type": "sale",
        "category": "base",
        "section": "当事人",
        "body": "甲方：{{party_a}}",
        "slot_instructions": [
            {"name": "party_a", "label": "甲方", "description": "d", "example": "x", "required": True}
        ],
        "law_refs": [],
        "tags": {},
        "level": "national",
        "source_path": "test/doc.docx",
        "source_doc_title": "T",
        "body_hash": "h1",
    }
    # `scenario` kwarg -> tags.scenario (scenario replaces the former region dim)
    sc = kw.pop("scenario", None)
    if sc:
        base["tags"] = {"scenario": sc}
    base.update(kw)
    return base


def test_upsert_and_list(seeded_db):
    upsert_clause(_clause(), db=seeded_db)
    rows = list_clauses("sale", db=seeded_db)
    assert len(rows) == 1
    assert rows[0]["section"] == "当事人"
    assert rows[0]["slot_instructions"][0]["name"] == "party_a"


def test_idempotent_upsert(seeded_db):
    upsert_clauses([_clause()], db=seeded_db)
    upsert_clauses([_clause()], db=seeded_db)
    assert len(list_clauses("sale", db=seeded_db)) == 1


def test_category_semantics(seeded_db):
    # custom -> source_path cleared
    cid = upsert_clause(_clause(category="custom", source_path="x", body_hash="c1"), db=seeded_db)
    custom = [c for c in list_clauses("sale", category="custom", db=seeded_db) if c["id"] == cid][0]
    assert custom["source_path"] is None
    assert custom["level"] is None
    # base -> level national (no region stripping anymore; region is gone)
    upsert_clause(_clause(category="base", body_hash="b1"), db=seeded_db)
    base = list_clauses("sale", category="base", db=seeded_db)[0]
    assert base["level"] == "national"
    assert "region" not in base["tags"]
    # tagged -> level local, scenario kept + filterable
    upsert_clause(
        _clause(category="tagged", scenario="农产品买卖", level="local", body_hash="t1"),
        db=seeded_db,
    )
    tagged = list_clauses("sale", category="tagged", tags={"scenario": "农产品买卖"}, db=seeded_db)
    assert len(tagged) == 1
    assert tagged[0]["level"] == "local"
    assert tagged[0]["tags"]["scenario"] == "农产品买卖"


def test_list_filters_and_ordering(seeded_db):
    upsert_clauses(
        [
            _clause(section="违约责任", category="base", body_hash="a"),
            _clause(section="当事人", category="base", body_hash="b"),
            _clause(section="当事人", category="tagged", scenario="农产品买卖", level="local", body_hash="c"),
            _clause(section="当事人", category="tagged", scenario="消费品零售", level="local", body_hash="d"),
        ],
        db=seeded_db,
    )
    # section ordering: 当事人 before 违约责任
    sections = [r["section"] for r in list_clauses("sale", db=seeded_db)]
    assert sections.index("当事人") < sections.index("违约责任")
    # scenario filter (scenario is a tag)
    jx = list_clauses("sale", category="tagged", tags={"scenario": "农产品买卖"}, db=seeded_db)
    assert len(jx) == 1 and jx[0]["tags"]["scenario"] == "农产品买卖"


def test_delete_clauses(seeded_db):
    upsert_clause(_clause(source_path="test/x.docx", body_hash="z"), db=seeded_db)
    n = delete_clauses("test/x.docx", db=seeded_db)
    assert n == 1
    assert list_clauses("sale", db=seeded_db) == []


def test_counts_by_type(seeded_db):
    upsert_clauses(
        [
            _clause(contract_type="sale", category="base", body_hash="1"),
            _clause(contract_type="sale", category="tagged", scenario="农产品买卖", level="local", body_hash="2"),
            _clause(contract_type="sale", category="tagged", scenario="农产品买卖", level="local", body_hash="3"),
            _clause(contract_type="loan", category="base", body_hash="4"),
        ],
        db=seeded_db,
    )
    rows = {r["contract_type"]: r for r in counts_by_type(db=seeded_db)}
    assert rows["sale"]["base"] == 1
    assert rows["sale"]["tagged"] == 2
    assert rows["sale"]["scenarios"] == ["农产品买卖"]
    assert rows["loan"]["base"] == 1
    cnt = count_clauses(db=seeded_db)
    assert cnt["total"] == 4 and cnt["base"] == 2 and cnt["tagged"] == 2
