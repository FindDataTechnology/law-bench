"""Unit tests for the pre-release coherence gate (src/clauses/coherence.py)."""

from __future__ import annotations

import pytest

from src.clauses.coherence import CoherenceError, validate_coherence


def _cl(section, body="x {{party_a}}", source="base"):
    return {"section": section, "body": body, "tags": {"source": source}, "id": 1}


def test_happy_path_passes():
    resolved = [_cl("当事人"), _cl("附则")]
    instr = [{"name": "party_a", "label": "a", "description": "", "example": "", "required": True}]
    # no error
    validate_coherence(resolved, "## 当事人\n\n甲 {{party_a}}", instr, {"当事人", "附则"})


def test_missing_canonical_section_fails():
    resolved = [_cl("当事人")]  # base defined 附则 but it was dropped
    instr = [{"name": "party_a", "label": "a", "description": "", "example": "", "required": True}]
    with pytest.raises(CoherenceError, match="missing canonical sections"):
        validate_coherence(resolved, "## 当事人\n\n甲 {{party_a}}", instr, {"当事人", "附则"})


def test_uninstructed_slot_fails():
    resolved = [_cl("当事人", body="甲 {{foo}}")]
    instr = [{"name": "party_a", "label": "a", "description": "", "example": "", "required": True}]
    with pytest.raises(CoherenceError, match="un-instructed slots: .*foo"):
        validate_coherence(resolved, "## 当事人\n\n甲 {{foo}}", instr, {"当事人"})


def test_duplicate_section_fails():
    resolved = [_cl("当事人"), _cl("当事人", body="dup {{party_a}}", source="tagged")]
    instr = [{"name": "party_a", "label": "a", "description": "", "example": "", "required": True}]
    with pytest.raises(CoherenceError, match="duplicate sections"):
        validate_coherence(resolved, "## 当事人\n\n甲 {{party_a}}", instr, {"当事人"})


def test_no_base_sections_skips_missing_check():
    # when base_sections is None (no base), the missing-section check is skipped
    resolved = [_cl("当事人", body="甲 {{party_a}}", source="tagged")]
    instr = [{"name": "party_a", "label": "a", "description": "", "example": "", "required": True}]
    validate_coherence(resolved, "## 当事人\n\n甲 {{party_a}}", instr, None)


def test_multiple_errors_all_reported():
    resolved = []  # missing section + (no dup) but body has uninstructed slot
    instr = []
    with pytest.raises(CoherenceError) as exc:
        validate_coherence(resolved, "## 当事人\n\n甲 {{foo}}", instr, {"当事人"})
    msg = str(exc.value)
    assert "missing canonical sections" in msg
    assert "un-instructed slots" in msg
