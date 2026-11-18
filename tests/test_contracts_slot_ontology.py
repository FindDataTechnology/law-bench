"""Tests for the slot ontology (src/contracts/slot_ontology.py) and write-time
slot normalization (src/clauses/store.py:_finalize)."""

from __future__ import annotations

from src.clauses.store import upsert_clause
from src.contracts.slot_ontology import (
    canonicalize_slot,
    instruction_for_slot,
    normalize_body_slots,
)


# --- canonicalize_slot ---

def test_canonicalize_role_name_to_party():
    assert canonicalize_slot("seller_name", "sale") == "party_a"
    assert canonicalize_slot("buyer_name", "sale") == "party_b"
    assert canonicalize_slot("party_a_name", "sale") == "party_a"


def test_canonicalize_role_attribute_compound():
    assert canonicalize_slot("buyer_address", "sale") == "party_b_address"
    assert canonicalize_slot("lessor_address", "lease") == "party_a_address"
    assert canonicalize_slot("party_a_legal_representative", "sale") == "party_a_legal_rep"


def test_canonicalize_synonym_concept():
    assert canonicalize_slot("legal_representative") == "legal_rep"
    assert canonicalize_slot("copy_count") == "contract_copies"
    assert canonicalize_slot("party_a_tax_id", "sale") == "party_a_credit_code"


def test_canonicalize_unknown_unchanged():
    assert canonicalize_slot("obscure_xyz_slot") == "obscure_xyz_slot"


def test_canonicalize_core_unchanged():
    for s in ("party_a", "party_b", "subject", "amount", "sign_date"):
        assert canonicalize_slot(s) == s


# --- instruction_for_slot ---

def test_instruction_for_core_and_concept():
    assert instruction_for_slot("party_a")["label"] == "甲方名称"
    assert instruction_for_slot("party_b_address", "sale")["label"] == "乙方联系地址"
    assert instruction_for_slot("legal_representative")["name"] == "legal_rep"


def test_instruction_for_unknown_is_none():
    assert instruction_for_slot("obscure_xyz_slot") is None


# --- normalize_body_slots ---

def test_normalize_body_slots_rewrites_all():
    body = "出卖人：{{seller_name}}，地址 {{seller_address}}，仲裁 {{arbitration_commission}}"
    out = normalize_body_slots(body, "sale")
    assert "{{party_a}}" in out
    assert "{{party_a_address}}" in out
    assert "{{arbitration_commission}}" in out
    assert "seller_name" not in out


# --- write-time normalization (store._finalize) ---

def test_upsert_normalizes_body_and_instructions(seeded_db):
    cid = upsert_clause(
        {
            "contract_type": "sale", "category": "tagged", "section": "当事人",
            "body": "卖方：{{seller_name}}，地址 {{seller_address}}",
            "slot_instructions": [
                {"name": "seller_name", "label": "卖方", "description": "d", "example": "x", "required": True},
                {"name": "seller_address", "label": "地址", "description": "d", "example": "x", "required": False},
            ],
            "law_refs": [], "tags": {"scenario": "家具买卖"}, "source_path": "t/norm.docx",
            "source_doc_title": "T", "body_hash": "x",
        },
        db=seeded_db,
    )
    c = seeded_db.execute(
        "SELECT body, slot_instructions FROM clauses WHERE id = %s", (cid,)
    ).fetchone()
    assert "{{party_a}}" in c["body"] and "seller_name" not in c["body"]
    assert "{{party_a_address}}" in c["body"]
    names = {i["name"] for i in c["slot_instructions"]}
    assert "party_a" in names and "party_a_address" in names
    assert "seller_name" not in names
