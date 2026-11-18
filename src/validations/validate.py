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
        "severity, law_ref, inherited_from "
        "FROM type_validations WHERE contract_type = %s ORDER BY id",
        (contract_type,),
    ).fetchall()
    return [dict(r) for r in rows]


def _provenance(contract_type: str, constraint: dict) -> dict:
    """单条结论的溯源三件套（契约见 fd-lex/contracts/lex-artifact.schema.json）。

    - ``source``：这条约束从哪来。继承来的写明上级类型（``inherited_from``），
      否则就是本类型的约束表——两者都指得出具体来源，不是"系统生成"这种空话。
    - ``stable_id``：``type_validations:<类型>#<约束 id>``。表名+主业务键，重灌不换号，
      案卷侧可以拿它对账"同一约束"。
    - ``as_of``：结论产生时刻（UTC ISO8601）。约束行本身没有时间戳列，
      所以这里如实标 ``as_of_source="run"``——它说明的是"此刻依据这套约束评的"，
      而不是"约束是哪年写的"；后者要有列才能说，不能编。
    """
    from src.eval.db import now_iso

    origin = constraint.get("inherited_from")
    source = f"type_validations:{origin}" if origin else f"type_validations:{contract_type}"
    return {
        "source": source,
        "stable_id": f"type_validations:{contract_type}#{constraint.get('constraint_id', '')}",
        "as_of": now_iso(),
        "as_of_source": "run",
    }


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

    Returns ``{errors: [...], warnings: [...], passed: bool,
    checked_constraints: int, degraded: bool[, degraded_reason]}``.
    Each entry: ``{constraint_id, message, law_ref, severity, provenance}``.

    ``passed = not errors`` —— 但**只有 ``checked_constraints > 0`` 时才有意义**。
    约束集为空（该 contract_type 尚未配置规则，或语料表为空）时 ``passed`` 恒为
    True，那只是"没有东西可违反"，**不是"查过且合规"**。2026-11-11 实测线上
    ``validation_list('sale')`` 返回 ``[]``，而 ``validation_check('sale')`` 回
    ``passed: true`` —— 法务产品把它读成"合同评审通过"是危险的假绿，故新增
    ``checked_constraints`` 与 ``degraded`` 把两态分开：``degraded=true`` 表示
    本次评审什么也没查，消费方 MUST NOT 据此声称合规。
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
            # 每条结论自带溯源：案卷侧要能从一条"不合规"反查到它依据哪条约束、
            # 那条约束来自哪张表/哪个上级类型。缺三件套即无法反查。
            "provenance": _provenance(contract_type, c),
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

    checked = len(_constraints)
    result: dict = {
        "errors": errors,
        "warnings": warnings,
        "passed": not errors,
        # 「没有可违反的约束」与「查过且合规」必须可分（见 docstring）。
        "checked_constraints": checked,
        "degraded": checked == 0,
    }
    if checked == 0:
        result["degraded_reason"] = (
            f"contract_type={contract_type!r} 未配置任何验证约束；"
            "passed=true 只表示没有可违反的约束，不代表已合规"
        )
    return result


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
