"""Evaluate assembled contracts against legal hard-limit constraints.

Public entry point: ``validate_draft(contract_type, draft, slots)``.
Reads from ``type_validations`` (populated by ``src.validations.load``).
NOT wired into generation — call this after assembly to check compliance.
"""

from __future__ import annotations

import re
from typing import Any

_KNOWN_KINDS = {
    "required", "always", "max", "min", "oneof",
    "regex", "max_duration", "max_deposit_months",
}


# ── value parsers ──────────────────────────────────────────────

def _to_number(val: Any) -> float | None:
    """Extract a numeric value from a slot value (``"3个月"`` → 3.0)."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return None
    m = re.search(r"[\d.]+", s)
    if m:
        try:
            return float(m.group())
        except ValueError:
            return None
    return None


def _parse_months(val: Any) -> float | None:
    """Parse a duration string to months (``"20年"`` → 240, ``"6个月"`` → 6)."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return None
    m = re.match(r"([\d.]+)\s*年", s)
    if m:
        return float(m.group(1)) * 12
    m = re.match(r"([\d.]+)\s*(?:个月|月)", s)
    if m:
        return float(m.group(1))
    m = re.match(r"([\d.]+)\s*天", s)
    if m:
        return float(m.group(1)) / 30
    try:
        return float(s)  # bare number → assume months
    except ValueError:
        return None


# ── single-constraint evaluator ────────────────────────────────

def _check_one(
    kind: str,
    field: str | None,
    params: dict,
    message: str,
    draft: str | None,
    slots: dict,
) -> bool:
    """Return True if the constraint passes."""
    if kind == "required":
        if not field:
            return True
        val = slots.get(field)
        return val is not None and str(val).strip() != ""

    if kind == "always":
        if draft is None:
            return False
        return message in draft

    if kind in ("max", "min"):
        if not field:
            return True
        num = _to_number(slots.get(field))
        if num is None:
            return True  # can't evaluate, don't fail
        bound = params.get("max" if kind == "max" else "min")
        if bound is None:
            bound = params.get("value")
        if bound is None:
            return True
        if kind == "max":
            return num <= float(bound)
        return num >= float(bound)

    if kind == "oneof":
        if not field:
            return True
        val = slots.get(field)
        if val is None:
            return True
        values = params.get("values") or []
        return str(val) in [str(v) for v in values]

    if kind == "regex":
        if not field:
            return True
        val = slots.get(field)
        if val is None:
            return True
        pattern = params.get("regex") or params.get("pattern")
        if not pattern:
            return True
        return re.search(pattern, str(val)) is not None

    if kind == "max_duration":
        if not field:
            return True
        val = slots.get(field)
        if val is None:
            return True
        months = _parse_months(val)
        if months is None:
            return True
        cap = params.get("max")
        if cap is not None:
            return months <= float(cap)
        years = params.get("years")
        if years is not None:
            return months <= float(years) * 12
        return True

    if kind == "max_deposit_months":
        deposit_field = params.get("deposit_field") or field
        if not deposit_field:
            return True
        val = slots.get(deposit_field)
        if val is None:
            return True
        months = _parse_months(val)
        if months is None:
            return True
        cap = params.get("max")
        if cap is None:
            return True
        return months <= float(cap)

    return True  # unknown — shouldn't reach here (filtered in caller)


# ── public API ──────────────────────────────────────────────────

def _load_constraints(contract_type: str) -> list[dict]:
    """Read merged constraints for ``contract_type`` from type_validations."""
    from src.eval.db import connect

    conn = connect(None)
    rows = conn.execute(
        "SELECT constraint_id, kind, field, params, message, "
        "severity, law_ref "
        "FROM type_validations WHERE contract_type = %s ORDER BY id",
        (contract_type,),
    ).fetchall()
    return [dict(r) for r in rows]


def validate_draft(
    contract_type: str,
    draft: str | None = None,
    slots: dict | None = None,
    _constraints: list[dict] | None = None,
) -> dict:
    """Evaluate a drafted contract against legal constraints.

    Parameters:
        contract_type: law-bench contract key (e.g. ``"sale"``).
        draft: assembled contract markdown (may be ``None``).
        slots: dict ``{slot_name: value}``.
        _constraints: internal — bypass DB (for self-check).

    Returns ``{errors: [...], warnings: [...], passed: bool}``.
    Each entry: ``{constraint_id, message, law_ref, severity}``.
    ``passed = not errors``.
    """
    if slots is None:
        slots = {}
    if _constraints is None:
        _constraints = _load_constraints(contract_type)

    errors: list[dict] = []
    warnings: list[dict] = []

    for c in _constraints:
        kind = c.get("kind", "")
        field = c.get("field")
        params = c.get("params") or {}
        message = c.get("message", "")
        severity = c.get("severity", "error")
        law_ref = c.get("law_ref")
        cid = c.get("constraint_id", "")

        entry = {
            "constraint_id": cid,
            "message": message,
            "law_ref": law_ref,
            "severity": severity,
        }

        if kind not in _KNOWN_KINDS:
            w = dict(entry)
            w["message"] = f"Unknown validation kind '{kind}': {message}"
            warnings.append(w)
            continue

        if not _check_one(kind, field, params, message, draft, slots):
            if severity == "error":
                errors.append(entry)
            else:
                warnings.append(entry)

    return {"errors": errors, "warnings": warnings, "passed": not errors}


# ── self-check ──────────────────────────────────────────────────

if __name__ == "__main__":
    test_constraints = [
        {"constraint_id": "req_amount", "kind": "required",
         "field": "借款金额", "params": {}, "message": "必须明确借款金额",
         "severity": "error", "law_ref": None},
        {"constraint_id": "max_deposit", "kind": "max",
         "field": "押金", "params": {"value": 3},
         "message": "押金不超过3", "severity": "warning", "law_ref": None},
        {"constraint_id": "rate_max", "kind": "always",
         "field": None, "params": {},
         "message": "借款利率不得超过LPR四倍", "severity": "warning",
         "law_ref": "最高法"},
    ]

    # Passing: required present, max within bound, always text in draft
    r = validate_draft(
        "loan",
        draft="本合同借款利率不得超过LPR四倍，双方确认。",
        slots={"借款金额": "10000元", "押金": "2"},
        _constraints=test_constraints,
    )
    assert r["passed"], f"expected pass, got: {r}"
    assert not r["errors"], f"expected no errors, got: {r['errors']}"
    print("PASS case OK")

    # Failing: required missing, max exceeded, always text absent
    r2 = validate_draft(
        "loan",
        draft="普通借款合同",
        slots={"押金": "5"},
        _constraints=test_constraints,
    )
    assert not r2["passed"], f"expected fail, got: {r2}"
    assert any(e["constraint_id"] == "req_amount" for e in r2["errors"])
    print("FAIL case OK")

    print("self-check OK")
