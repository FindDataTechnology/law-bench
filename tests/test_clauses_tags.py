"""Tests for the controlled-vocabulary tag layer (tags.py + store persistence)."""

from __future__ import annotations

import pytest

from src.clauses import TAG_VOCAB, register_tag_dim, validate_tags
from src.clauses.store import create_clause, list_clauses, update_clause


def test_vocab_has_starter_and_manifest_dims(seeded_db):
    # DB-backed vocab: the session fixture seeds tag_dims + load_vocab_from_db,
    # so the manifest-declared type-specific dims are present alongside the
    # starter set. (seeded_db is requested to trigger that session fixture.)
    universal = TAG_VOCAB.get(None, {})
    for k in ("source", "stance", "strength", "risk", "mandatory"):
        assert k in universal
    assert "special_restriction_period" in TAG_VOCAB.get("employment", {})  # employment
    assert "tech_achievement_ownership" in TAG_VOCAB.get("technology", {})  # technology


def test_register_tag_dim_grows_vocab():
    register_tag_dim(None, "test_dim_xyz", values=["a", "b"])
    assert "test_dim_xyz" in TAG_VOCAB.get(None, {})
    assert validate_tags({"test_dim_xyz": "a"}) == {"test_dim_xyz": "a"}


def test_validate_drops_unknown_key():
    assert validate_tags({"stance": "pro_a", "mood": "happy"}) == {"stance": "pro_a"}


def test_validate_region_dropped():
    # region (province) was retired; it is no longer a recognized dim
    assert validate_tags({"region": "吉林"}) == {}


def test_validate_scenario_lenient():
    # scenario is LLM-suggested/governed: any non-empty value is kept (the seeded
    # vocab is advisory, not a hard whitelist)
    assert validate_tags({"scenario": "全新业务场景"}, contract_type="sale") == {"scenario": "全新业务场景"}


def test_scenario_seeded_per_type(seeded_db):
    # seed_tag_dims (session fixture) seeds scenario from SCENARIO_VOCAB
    assert "农产品买卖" in TAG_VOCAB.get("sale", {}).get("scenario", [])
    assert "驾校培训" in TAG_VOCAB.get("service", {}).get("scenario", [])


def test_validate_rejects_bad_value():
    with pytest.raises(ValueError):
        validate_tags({"stance": "pro_A"})


def test_create_clause_persists_tags(seeded_db):
    cid = create_clause(
        {
            "contract_type": "sale",
            "category": "custom",
            "section": "附则",
            "body": "甲方：{{party_a}}。",
            "tags": {"stance": "pro_a", "strength": "strong"},
        },
        db=seeded_db,
    )
    c = [r for r in list_clauses("sale", db=seeded_db) if r["id"] == cid][0]
    assert c["tags"] == {"stance": "pro_a", "strength": "strong", "source": "custom"}


def test_body_edit_preserves_tags(seeded_db):
    cid = create_clause(
        {
            "contract_type": "sale",
            "category": "custom",
            "section": "附则",
            "body": "old {{x}}",
            "tags": {"stance": "pro_a"},
        },
        db=seeded_db,
    )
    upd = update_clause(
        cid,
        {"body": "new {{x}} 依据《民法典》。", "section": "当事人", "category": "custom"},
        db=seeded_db,
    )
    # body-derived fields re-derived, tags untouched (curatorial, not body-derived)
    assert upd["tags"] == {"stance": "pro_a", "source": "custom"}
    assert upd["body_hash"]


def test_update_clause_replaces_tags_when_supplied(seeded_db):
    cid = create_clause(
        {"contract_type": "sale", "category": "custom", "section": "附则",
         "body": "x {{a}}", "tags": {"stance": "pro_a"}},
        db=seeded_db,
    )
    upd = update_clause(cid, {"body": "x {{a}}", "section": "附则", "category": "custom",
                              "tags": {"stance": "pro_b"}}, db=seeded_db)
    assert upd["tags"] == {"stance": "pro_b", "source": "custom"}


def test_list_filter_by_tags(seeded_db):
    create_clause({"contract_type": "sale", "category": "custom", "section": "违约责任",
                   "body": "偏甲 {{a}}", "tags": {"stance": "pro_a"}}, db=seeded_db)
    create_clause({"contract_type": "sale", "category": "custom", "section": "违约责任",
                   "body": "偏乙 {{b}}", "tags": {"stance": "pro_b"}}, db=seeded_db)
    pro_a = list_clauses("sale", category="custom", tags={"stance": "pro_a"}, db=seeded_db)
    assert len(pro_a) == 1
    assert pro_a[0]["body"].startswith("偏甲")


def test_list_filter_by_type_specific_tag(seeded_db):
    # type-specific dim registered from manifests; usable as a filter
    create_clause({"contract_type": "sale", "category": "custom", "section": "附则",
                   "body": "x {{a}}", "tags": {"special_restriction_period": "non_compete"}},
                  db=seeded_db)
    rows = list_clauses("sale", tags={"special_restriction_period": "non_compete"}, db=seeded_db)
    assert len(rows) == 1
