"""Tests for tag review: is_assembly_ready, review_tag, bulk_review, assembly gate."""

from __future__ import annotations

import pytest

from src.clauses.assemble import _select_clauses
from src.clauses.store import create_clause, list_clauses
from src.clauses.tag_review import bulk_review, is_assembly_ready, list_pending, review_tag
from src.eval.errors import NotFoundError


def test_is_assembly_ready_all_approved():
    c = {"tags": {"stance": "pro_a", "source": "custom"},
         "tag_review": {"stance": "approved", "source": "approved"}}
    assert is_assembly_ready(c) is True


def test_is_assembly_ready_pending():
    c = {"tags": {"stance": "pro_a", "source": "custom"},
         "tag_review": {"stance": "approved", "source": "pending"}}
    assert is_assembly_ready(c) is False


def test_is_assembly_ready_no_tags():
    c = {"tags": {}, "tag_review": {}}
    assert is_assembly_ready(c) is True  # no tags = trivially ready


def test_is_assembly_ready_ignores_metadata_keys():
    """`_`-prefixed keys are importer metadata, not review dims."""
    c = {"tags": {"stance": "pro_a", "source": "custom"},
         "tag_review": {"stance": "approved", "source": "approved",
                        "_note": "auto-approved-pilot"}}
    assert is_assembly_ready(c) is True

    # a `_` dim in tags must not create a phantom gate either
    c = {"tags": {"stance": "approved", "_imported_at": "2026-08-17"},
         "tag_review": {"stance": "approved"}}
    assert is_assembly_ready(c) is True


def test_is_assembly_ready_missing_dim_blocks():
    """A genuine dim absent from tag_review still blocks (e.g. #421/#423)."""
    c = {"tags": {"stance": "pro_a", "source": "custom", "legal_topic": "x"},
         "tag_review": {"stance": "approved", "source": "approved",
                        "_note": "auto-approved-pilot"}}
    assert is_assembly_ready(c) is False


def test_review_tag_per_dim(seeded_db):
    cid = create_clause(
        {"contract_type": "sale", "category": "custom", "section": "附则",
         "body": "test {{a}}", "tags": {"stance": "pro_a", "source": "custom"}},
        db=seeded_db,
    )
    # initially tag_review is {} -> not ready
    c = [r for r in list_clauses("sale", db=seeded_db) if r["id"] == cid][0]
    assert is_assembly_ready(c) is False
    # approve stance only -> still not ready (source pending)
    review_tag(cid, "stance", "approved", db=seeded_db)
    c = [r for r in list_clauses("sale", db=seeded_db) if r["id"] == cid][0]
    assert is_assembly_ready(c) is False
    # approve source -> ready
    review_tag(cid, "source", "approved", db=seeded_db)
    c = [r for r in list_clauses("sale", db=seeded_db) if r["id"] == cid][0]
    assert is_assembly_ready(c) is True


def test_bulk_review(seeded_db):
    cid = create_clause(
        {"contract_type": "sale", "category": "custom", "section": "附则",
         "body": "test {{a}}", "tags": {"stance": "pro_a", "source": "custom"}},
        db=seeded_db,
    )
    bulk_review(cid, "approved", db=seeded_db)
    c = [r for r in list_clauses("sale", db=seeded_db) if r["id"] == cid][0]
    assert is_assembly_ready(c) is True
    assert c["tag_review"]["stance"] == "approved"
    assert c["tag_review"]["source"] == "approved"


def test_bulk_review_preserves_metadata_keys(seeded_db):
    """Bulk review merges: `_`-prefixed provenance keys survive."""
    cid = create_clause(
        {"contract_type": "sale", "category": "custom", "section": "附则",
         "body": "test {{a}}", "tags": {"stance": "pro_a", "source": "custom"},
         "tag_review": {"_note": "auto-approved-pilot"}},
        db=seeded_db,
    )
    bulk_review(cid, "approved", db=seeded_db)
    c = [r for r in list_clauses("sale", db=seeded_db) if r["id"] == cid][0]
    assert c["tag_review"]["_note"] == "auto-approved-pilot"
    assert c["tag_review"]["stance"] == "approved"


def test_review_tag_rejects_metadata_dim(seeded_db):
    cid = create_clause(
        {"contract_type": "sale", "category": "custom", "section": "附则",
         "body": "test {{a}}", "tags": {"stance": "pro_a", "source": "custom"}},
        db=seeded_db,
    )
    with pytest.raises(ValueError):
        review_tag(cid, "_imported_at", "approved", db=seeded_db)


def test_review_tag_not_found(seeded_db):
    with pytest.raises(NotFoundError):
        review_tag(999999, "stance", "approved", db=seeded_db)


def test_assembly_gates_custom_by_review(seeded_db):
    """Only assembly-ready custom clauses are included in assembly."""
    cid1 = create_clause(
        {"contract_type": "sale", "category": "custom", "section": "违约责任",
         "body": "approved-marker {{a}}", "tags": {"stance": "pro_a", "source": "custom"}},
        db=seeded_db,
    )
    bulk_review(cid1, "approved", db=seeded_db)

    cid2 = create_clause(
        {"contract_type": "sale", "category": "custom", "section": "违约责任",
         "body": "pending-marker {{b}}", "tags": {"stance": "pro_a", "source": "custom"}},
        db=seeded_db,
    )
    # cid2 not reviewed -> not assembly-ready

    selected, _, _ = _select_clauses("sale", None, None, stance="pro_a", db=seeded_db)
    bodies = [c["body"] for c in selected]
    assert any("approved-marker" in b for b in bodies)
    assert not any("pending-marker" in b for b in bodies)


def test_list_pending(seeded_db):
    cid = create_clause(
        {"contract_type": "sale", "category": "custom", "section": "附则",
         "body": "test {{a}}", "tags": {"stance": "pro_a", "source": "custom"},
         "tag_review": {"stance": "pending", "source": "pending"}},
        db=seeded_db,
    )
    pending = list_pending("sale", db=seeded_db)
    assert any(c["id"] == cid for c in pending)
    # approve all -> not in pending anymore
    bulk_review(cid, "approved", db=seeded_db)
    pending = list_pending("sale", db=seeded_db)
    assert not any(c["id"] == cid for c in pending)
