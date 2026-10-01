"""Tests for seed manifest load/validate + the idempotent loader."""

from __future__ import annotations

import pytest

from src.clauses.seed_manifest import clause_to_record, load_manifest, load_one
from src.clauses.store import list_clauses


def test_load_employment_manifest(seeded_db):
    n = load_one("employment", db=seeded_db)
    assert n == 4  # employment pilot has 4 clauses
    rows = list_clauses("employment", category="custom", db=seeded_db)
    assert len(rows) == 4
    non_compete = [r for r in rows if "竞业" in r["body"]][0]
    assert non_compete["manual"] is True
    assert non_compete["tags"].get("stance") == "pro_a"
    assert non_compete["source_doc_title"] == "seed:employment"
    # curated slot_instructions preserved (not stubbed)
    names = {s["name"] for s in non_compete["slot_instructions"]}
    assert "non_compete_months" in names


def test_load_one_is_idempotent(seeded_db):
    load_one("employment", db=seeded_db)
    n2 = load_one("employment", db=seeded_db)
    assert n2 == 4
    rows = list_clauses("employment", category="custom", db=seeded_db)
    assert len(rows) == 4  # delete-by-marker -> no duplicates


def test_clause_to_record_builds_tags_and_passes_slots():
    rec = clause_to_record(
        {
            "section": "违约责任",
            "body": "x {{a}}",
            "stance": "pro_a",
            "strength": "strong",
            "slot_instructions": [
                {"name": "a", "label": "A", "description": "d", "example": "e", "required": True}
            ],
        },
        "sale",
        "seed:sale",
    )
    assert rec["tags"] == {"stance": "pro_a", "strength": "strong"}
    assert rec["category"] == "custom"
    assert rec["source_doc_title"] == "seed:sale"
    assert rec["slot_instructions"][0]["label"] == "A"


def test_bad_manifest_unknown_section_rejected(tmp_path):
    bad = tmp_path / "sale.yaml"
    bad.write_text(
        "contract_type: sale\nclauses:\n"
        "  - family: x\n    section: 不存在的章节\n    body: a\n    why: r\n    verdict: real\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_manifest(bad)


def test_bad_manifest_missing_slot_instruction_rejected(tmp_path):
    bad = tmp_path / "loan.yaml"
    bad.write_text(
        "contract_type: loan\nclauses:\n"
        "  - family: x\n    section: 附则\n    body: a {{s}}\n    why: r\n    verdict: real\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_manifest(bad)


def test_bad_manifest_bad_stance_rejected(tmp_path):
    bad = tmp_path / "sale.yaml"
    bad.write_text(
        "contract_type: sale\nclauses:\n"
        "  - family: x\n    section: 附则\n    body: a {{s}}\n    stance: pro_A\n"
        "    slot_instructions:\n      - {name: s}\n    why: r\n    verdict: real\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_manifest(bad)
