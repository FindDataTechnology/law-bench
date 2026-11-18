"""Tests for the /clauses web routes (src/web/routes/clauses.py)."""

from __future__ import annotations

import pytest

from src.clauses.store import upsert_clause


def _seed(seeded_db) -> None:
    upsert_clause(
        {
            "contract_type": "sale", "category": "base", "section": "当事人",
            "body": "甲方：{{party_a}}",
            "slot_instructions": [{"name": "party_a", "label": "甲方", "description": "d", "example": "x", "required": True}],
            "law_refs": [], "level": "national", "source_path": "t/base.docx",
            "source_doc_title": "T", "body_hash": "b1",
        },
        db=seeded_db,
    )


def test_clauses_list(app_client, seeded_db):
    _seed(seeded_db)
    r = app_client.get("/clauses")
    assert r.status_code == 200
    assert "条款库" in r.text
    assert "sale" in r.text


def test_clauses_detail(app_client, seeded_db):
    _seed(seeded_db)
    r = app_client.get("/clauses/sale")
    assert r.status_code == 200
    assert "当事人" in r.text


def test_clauses_detail_unknown_type(app_client):
    r = app_client.get("/clauses/does_not_exist")
    assert r.status_code == 404


def test_clauses_generate_docx(app_client, seeded_db):
    _seed(seeded_db)
    r = app_client.get("/clauses/sale/generate", params={"format": "docx"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert len(r.content) > 0


def test_clauses_generate_unknown_type(app_client):
    r = app_client.get("/clauses/does_not_exist/generate", params={"format": "docx"})
    assert r.status_code == 404


def test_clauses_generate_bad_format(app_client, seeded_db):
    _seed(seeded_db)
    r = app_client.get("/clauses/sale/generate", params={"format": "rtf"})
    assert r.status_code == 400
