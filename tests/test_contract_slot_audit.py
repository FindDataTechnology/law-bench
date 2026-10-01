"""Tests for the contract 母版 slot-coverage evaluator (``src/contracts/audit.py``)
and its CLI (``python -m src.contracts audit``).

Hermetic: no LLM, no database, no network. ``audit_body`` is exercised with
synthetic bodies; ``audit_all`` reads the committed registry file only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.contracts.audit import (
    BODY_PROPER_SLOTS,
    TAIL_ALLOWED_SLOTS,
    AuditReport,
    TemplateAudit,
    audit_all,
    audit_body,
    audit_template,
    build_aggregate,
)
from src.contracts.cli import main as cli_main
from src.contracts.slots import REQUIRED_SLOTS, default_slot_instructions
from src.eval.errors import NotFoundError


# --- helpers ---------------------------------------------------------------- #


def _instr(extra: list[str] | None = None, drop: list[str] | None = None) -> list[dict]:
    """Build a slot_instructions manifest from the default, optionally adding
    custom-named entries or dropping some."""
    base = {si["name"]: si for si in default_slot_instructions("买卖合同")}
    for n in drop or []:
        base.pop(n, None)
    for n in extra or []:
        base[n] = {"name": n, "label": n, "description": "", "example": "", "required": False}
    return list(base.values())


def _body(head_slots=(), tail_slots=()) -> str:
    head = "甲方：" + "".join("{{" + s + "}}" for s in head_slots) + "\n"
    if not tail_slots:
        return head
    return head + "\n## 签署信息\n" + "\n".join("{{" + s + "}}" for s in tail_slots) + "\n"


# --- 4.1 all present -------------------------------------------------------- #


def test_audit_body_all_required_in_head_passes():
    body = _body(head_slots=REQUIRED_SLOTS)
    res = audit_body(body, _instr(), key="sale", zh="买卖合同")
    assert res.status == "pass"
    assert res.coverage == 1.0
    assert set(res.present) == set(REQUIRED_SLOTS)
    assert res.missing == []
    assert res.tail_only == []
    assert res.extra_slots == []
    assert res.orphan_instructions == []


# --- 4.2 missing party_b ---------------------------------------------------- #


def test_audit_body_missing_party_b_fails():
    slots = [s for s in REQUIRED_SLOTS if s != "party_b"]
    res = audit_body(_body(head_slots=slots), _instr(), key="x", zh="X")
    assert "party_b" in res.missing
    assert res.status == "fail"
    assert res.coverage < 1.0


# --- 4.3 tail-only placement ------------------------------------------------ #


def test_audit_body_party_a_tail_only_fails():
    head = [s for s in REQUIRED_SLOTS if s != "party_a"]
    res = audit_body(_body(head_slots=head, tail_slots=["party_a"]), _instr(), key="x", zh="X")
    assert "party_a" in res.tail_only
    assert res.status == "fail"


def test_audit_body_sign_date_tail_only_does_not_fail():
    head = [s for s in REQUIRED_SLOTS if s != "sign_date"]
    res = audit_body(_body(head_slots=head, tail_slots=["sign_date"]), _instr(), key="x", zh="X")
    assert "sign_date" in res.tail_only
    assert "sign_date" not in res.missing
    assert res.status == "pass"


def test_tail_allowed_and_body_proper_partition_required_slots():
    assert set(TAIL_ALLOWED_SLOTS) | set(BODY_PROPER_SLOTS) == set(REQUIRED_SLOTS)
    assert set(TAIL_ALLOWED_SLOTS).isdisjoint(BODY_PROPER_SLOTS)


# --- 4.4 extra / orphan ----------------------------------------------------- #


def test_audit_body_extra_slot_flagged():
    body = _body(head_slots=(*REQUIRED_SLOTS, "property_name"))
    res = audit_body(body, _instr(), key="x", zh="X")
    assert "property_name" in res.extra_slots
    assert res.status == "pass"  # extras are warnings, not failures


def test_audit_body_orphan_instruction_flagged():
    body = _body(head_slots=REQUIRED_SLOTS)
    res = audit_body(body, _instr(extra=["custom_field"]), key="x", zh="X")
    assert "custom_field" in res.orphan_instructions
    assert res.status == "pass"


# --- 4.5 audit_all aggregate ------------------------------------------------ #


def test_audit_all_aggregate_counts_missing_and_failing(monkeypatch):
    from src.contracts import audit as audit_mod

    fake = [
        TemplateAudit(
            key="a", zh="A", status="fail", coverage=0.9,
            present=[], tail_only=[], missing=["party_b"],
            extra_slots=[], orphan_instructions=[],
        ),
        TemplateAudit(
            key="b", zh="B", status="pass", coverage=1.0,
            present=[], tail_only=[], missing=[],
            extra_slots=[], orphan_instructions=[],
        ),
    ]
    monkeypatch.setattr(audit_mod, "list_contract_types", lambda: [{"key": "a", "zh": "A"}, {"key": "b", "zh": "B"}])
    monkeypatch.setattr(audit_mod, "audit_template", lambda k: next(t for t in fake if t.key == k))

    rep = audit_all()
    assert rep.aggregate["by_slot"]["party_b"] == 1
    assert rep.aggregate["failing_templates"] == ["a"]
    assert rep.aggregate["failed"] == 1
    assert rep.aggregate["passed"] == 1
    assert rep.aggregate["total"] == 2


def test_build_aggregate_by_slot_counts_across_templates():
    audits = [
        TemplateAudit(key="a", zh="A", status="fail", coverage=0.0, missing=["party_b"], present=[], tail_only=[], extra_slots=[], orphan_instructions=[]),
        TemplateAudit(key="b", zh="B", status="fail", coverage=0.0, missing=["party_b"], present=[], tail_only=[], extra_slots=[], orphan_instructions=[]),
    ]
    agg = build_aggregate(audits)
    assert agg["by_slot"]["party_b"] == 2
    assert agg["failing_templates"] == ["a", "b"]


# --- 4.7 regression over the real registry ---------------------------------- #


def test_audit_all_real_registry_has_no_failures():
    rep = audit_all()
    assert rep.aggregate["failed"] == 0
    assert rep.aggregate["failing_templates"] == []
    assert rep.aggregate["total"] == len(rep.templates)


def test_audit_template_unknown_raises():
    with pytest.raises(NotFoundError):
        audit_template("does_not_exist")


# --- 4.6 & 4.8 CLI ---------------------------------------------------------- #


def test_cli_audit_default_prints_summary(capsys):
    rc = cli_main(["audit"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "total=" in out
    assert "passed=" in out
    assert "failed=" in out


def test_cli_audit_single_type(capsys, tmp_path):
    rc = cli_main(["audit", "--type", "sale", "--out", str(tmp_path / "r.json")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "sale" in out


def test_cli_audit_json_emits_valid_json(capsys, tmp_path):
    rc = cli_main(["audit", "--json", "--type", "sale", "--out", str(tmp_path / "r.json")])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)  # stdout is a single valid JSON object
    assert payload["templates"][0]["key"] == "sale"
    assert "aggregate" in payload


def test_cli_audit_strict_exits_nonzero_on_failure(monkeypatch, tmp_path):
    failing = TemplateAudit(
        key="bad", zh="坏", status="fail", coverage=0.0,
        present=[], tail_only=[], missing=["party_a"],
        extra_slots=[], orphan_instructions=[],
    )
    report = AuditReport(templates=[failing], aggregate={"missing_templates": []})
    monkeypatch.setattr("src.contracts.cli.audit_all", lambda: report)

    rc_strict = cli_main(["audit", "--strict", "--out", str(tmp_path / "r1.json")])
    assert rc_strict == 1

    rc_loose = cli_main(["audit", "--out", str(tmp_path / "r2.json")])
    assert rc_loose == 0


def test_cli_audit_out_writes_report_artifact(tmp_path):
    out_path = tmp_path / "contract_slot_audit.json"
    rc = cli_main(["audit", "--out", str(out_path), "--type", "sale"])
    assert rc == 0
    assert out_path.exists()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert "aggregate" in payload
    assert "templates" in payload
    agg = payload["aggregate"]
    for key in ("total", "passed", "failed", "failing_templates", "by_slot"):
        assert key in agg
    assert payload["templates"][0]["key"] == "sale"
