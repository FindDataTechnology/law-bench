"""Tests for the contract-template tool: registry, slot instructions, per-type
法律法规 extraction, DOCX/PDF generation, and the CLI (``python -m src.contracts``).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.contracts import (
    check_slot_consistency,
    extract_laws_for_type,
    generate_contract,
    get_slot_instructions,
    get_template,
    list_contract_types,
)
from src.generator import SLOT_PATTERN, find_slots
from src.eval.errors import NotFoundError

REPO_ROOT = Path(__file__).resolve().parents[1]
SOFFICE_AVAILABLE = shutil.which("soffice") is not None


# --- registry --------------------------------------------------------------- #


def test_list_contract_types_has_43_in_order():
    types = list_contract_types()
    assert len(types) == 43
    assert types[0] == {"key": "sale", "zh": "买卖合同"}
    # every entry has the expected shape
    assert all({"key", "zh"} <= set(t) for t in types)


def test_get_template_fields_and_slots():
    t = get_template("sale")
    assert t["type"] == "sale"
    assert t["zh_name"] == "买卖合同"
    assert t["body"].strip()
    # bodies are LLM-drafted (order varies), so assert the slot SET, not order
    assert len(t["slots"]) == 12
    assert set(t["slots"]) == {
        "party_a", "party_b", "subject", "amount", "term_start", "term_end",
        "party_a_duty", "party_b_duty", "penalty", "jurisdiction",
        "sign_date", "sign_location",
    }


def test_get_template_for_newly_added_types():
    """land_transfer / service were added to contract_types without a 母版; both
    now ship a skeleton body covering all 12 required slots."""
    required = {
        "party_a", "party_b", "subject", "amount", "term_start", "term_end",
        "party_a_duty", "party_b_duty", "penalty", "jurisdiction",
        "sign_date", "sign_location",
    }
    for key in ("land_transfer", "service"):
        t = get_template(key)
        assert t["type"] == key
        assert set(t["slots"]) == required


def test_get_template_unknown_raises():
    with pytest.raises(NotFoundError):
        get_template("does_not_exist")


# --- slot instructions ------------------------------------------------------ #


def test_slot_instructions_cover_exactly_template_slots():
    tmpl = get_template("sale")
    instr = get_slot_instructions("sale")
    assert {si["name"] for si in instr} == set(tmpl["slots"])


def test_slot_instruction_fields_populated():
    for si in get_slot_instructions("sale"):
        assert si["label"]
        assert si["description"]
        assert "example" in si
        assert isinstance(si["required"], bool)


def test_slot_consistency_all_types():
    bad = []
    for t in list_contract_types():
        missing, extra = check_slot_consistency(t["key"])
        if missing or extra:
            bad.append((t["key"], missing, extra))
    assert bad == [], f"inconsistent slot/instruction sets: {bad}"


def test_get_slot_instructions_unknown_raises():
    with pytest.raises(NotFoundError):
        get_slot_instructions("does_not_exist")


def test_normalize_body_strips_unknown_and_appends_missing():
    from src.contracts.templates import normalize_body

    required = ["party_a", "sign_date"]
    raw = "# 买卖合同\n\n甲方：{{party_a}}\n\n无关占位：{{oops}}\n"
    body = normalize_body(raw, required)
    assert "{{oops}}" not in body  # unknown token removed
    assert "{{party_a}}" in body  # kept
    assert "{{sign_date}}" in body  # missing required slot appended
    assert not body.startswith("# ")  # leading H1 title stripped
    assert set(SLOT_PATTERN.findall(body)) == set(required)


# --- legal extraction ------------------------------------------------------- #


def test_extract_laws_for_type_sale():
    laws = extract_laws_for_type("sale")
    assert laws, "expected non-empty law list for sale"
    for law in laws:
        assert law["name"]
        assert law["category"] in ("core_law", "judicial_interpretation", "special_statute", "procedural", "other")
        assert law["category_zh"]
        assert set(law["sources"]) <= {"doubao", "deepseek"}
        assert law["sources"]  # at least one source


def test_extract_laws_for_type_unknown_raises():
    with pytest.raises(NotFoundError):
        extract_laws_for_type("does_not_exist")


# --- generation ------------------------------------------------------------- #


def test_generate_contract_docx(tmp_path):
    r = generate_contract("sale", format="docx", out_dir=tmp_path)
    assert r["docx_path"] and Path(r["docx_path"]).exists()
    assert r["pdf_path"] is None
    assert r["slots"] and r["instructions"] and r["laws"]
    # slots are present as unfilled placeholders in the generated DOCX
    assert find_slots(r["docx_path"]) == get_template("sale")["slots"]


def test_generate_contract_unknown_raises(tmp_path):
    with pytest.raises(NotFoundError):
        generate_contract("does_not_exist", format="docx", out_dir=tmp_path)


def test_generate_contract_unsupported_format_raises(tmp_path):
    with pytest.raises(ValueError):
        generate_contract("sale", format="rtf", out_dir=tmp_path)


@pytest.mark.skipif(not SOFFICE_AVAILABLE, reason="libreoffice (soffice) not installed")
def test_generate_contract_both(tmp_path):
    r = generate_contract("sale", format="both", out_dir=tmp_path)
    assert Path(r["docx_path"]).exists()
    assert Path(r["pdf_path"]).exists() and Path(r["pdf_path"]).stat().st_size > 0


@pytest.mark.skipif(not SOFFICE_AVAILABLE, reason="libreoffice (soffice) not installed")
def test_generate_contract_pdf_only(tmp_path):
    r = generate_contract("sale", format="pdf", out_dir=tmp_path)
    assert r["docx_path"] is None
    assert Path(r["pdf_path"]).exists() and Path(r["pdf_path"]).stat().st_size > 0
    # pdf-only must not leave a stray docx in the output dir
    assert not (tmp_path / "sale.docx").exists()


# --- CLI -------------------------------------------------------------------- #


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "src.contracts", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )


def test_cli_single_docx(tmp_path):
    out = tmp_path / "out"
    res = _run_cli("sale", "--format", "docx", "--out", str(out))
    assert res.returncode == 0, res.stderr
    paths = [ln for ln in res.stdout.splitlines() if ln.strip()]
    assert len(paths) == 1
    assert Path(paths[0]).exists()


def test_cli_all_docx(tmp_path):
    out = tmp_path / "all"
    res = _run_cli("--all", "--format", "docx", "--out", str(out))
    assert res.returncode == 0, res.stderr
    paths = [ln for ln in res.stdout.splitlines() if ln.strip()]
    assert len(paths) == 43
    assert all(Path(p).exists() for p in paths)


def test_cli_unknown_type_exits_nonzero():
    res = _run_cli("does_not_exist", "--format", "docx")
    assert res.returncode != 0
    assert "does_not_exist" in res.stderr
