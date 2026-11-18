"""Template readiness: rubrics must resolve, and a new version must not be worse.

Two rules, both about the same gap — until this module existed, a template's
``rubric_refs`` was a comment. ``src/bench/templates.py`` never looked at it, so
"this template is judged by these rulers" was unverifiable prose, and
``update_template`` wrote ``max(version) + 1`` with nothing standing between a
good version and a worse one.

Saving is deliberately permissive and instantiating is not:

- saving reports what did not resolve, so a template can be built in steps
  (vocabulary first, rulers second);
- instantiating requires every ref to resolve, because that is the moment a
  domain starts relying on the template. A template nobody can measure can
  never show that it got better.

The novelty gate lives here rather than inside ``update_template`` on purpose:
the gate reads the verdict ledger (a cross-module query), and pushing that into
the low-level writer would make every test that creates a template also have to
prepare a ledger.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from . import domain_rubrics

#: The gate a template promotion is judged by. The ledger owns the closed set of
#: gates; this is the one that answers "is the new version any worse".
PROMOTION_GATE = "no-worse"


def rubric_refs(schema: dict) -> list[str]:
    """The declared ruler identifiers, or ``[]`` when the template declares none."""
    refs = (schema or {}).get("rubric_refs")
    if not isinstance(refs, list):
        return []
    return [str(r).strip() for r in refs if isinstance(r, str) and r.strip()]


def rubric_digest(schema: dict) -> Optional[str]:
    """Content-only digest of the ruler *set*, or ``None`` when none declared.

    Sorted names only — no timestamps, no publisher. Two templates judged by the
    same rulers produce the same digest, otherwise every verdict would look like
    a changed measuring stick and no history would ever be comparable.
    """
    refs = sorted(set(rubric_refs(schema)))
    if not refs:
        return None
    payload = json.dumps(refs, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def unresolvable_refs(conn: Any, *, domain_path: str, schema: dict) -> list[str]:
    """Refs that name no rubric the domain can actually use.

    Resolution is against the *effective* set (own + inherited) — what a reviewer
    sees on the domain page. Checking a different set would report a ruler as
    missing while the console shows it.
    """
    refs = rubric_refs(schema)
    if not refs:
        return []
    available = {
        r["name"] for r in domain_rubrics.effective_rubrics(conn, domain_path=domain_path)
    }
    return [r for r in refs if r not in available]


def readiness(conn: Any, *, domain_path: str, schema: dict) -> dict:
    """What the quality view reports: declared / resolved / rate.

    ``rate`` is ``None`` — not ``0`` and not ``1`` — when nothing was declared.
    A zero denominator rendered as a percentage reads as "all good", which is the
    exact failure this module exists to prevent.
    """
    refs = rubric_refs(schema)
    missing = unresolvable_refs(conn, domain_path=domain_path, schema=schema)
    declared = len(refs)
    resolved = declared - len(missing)
    return {
        "declared": declared,
        "resolved": resolved,
        "missing": missing,
        "rate": (resolved / declared) if declared else None,
        "digest": rubric_digest(schema),
    }


def instance_problem(conn: Any, *, domain_path: str, schema: dict) -> Optional[str]:
    """Why this template may not become a domain, or ``None`` when it may."""
    if not rubric_refs(schema):
        return (
            "模板未声明任何尺子（rubric_refs 为空）：不可实例化为正式域。"
            "先挂上至少一把评测尺子，否则该域永远无法证明自己没有变差。"
        )
    missing = unresolvable_refs(conn, domain_path=domain_path, schema=schema)
    if missing:
        return "模板声明的尺子无法解析：" + "、".join(missing)
    return None


# --------------------------------------------------------------- novelty gate


def _latest_verdict(conn: Any, template_name: str) -> Optional[dict]:
    """The newest ``no-worse`` verdict for this template, read on the caller's conn.

    ``db_path=conn`` is load-bearing: without it ``list_verdicts`` falls back to
    the process-wide cached connection, which in a test run belongs to whichever
    database connected first — the ledger would then be read from the wrong one
    and the gate would answer confidently about somebody else's rows.
    """
    from src.eval.store import list_verdicts

    rows = list_verdicts(
        subject_kind="template", subject_key=template_name, db_path=conn
    )
    for row in rows or []:
        if (row.get("gate") or PROMOTION_GATE) == PROMOTION_GATE:
            return row
    return None


def promotion_problem(
    conn: Any, *, template_name: str, new_schema: dict, prev_schema: Optional[dict]
) -> Optional[str]:
    """Why the next version may not ship, or ``None`` when it may.

    Three outcomes, and the middle one is the whole reason the ledger has three
    states: "could not tell" must never be read as "did not fail".

    Dropping the rulers is itself a regression: without this branch, the way to
    ship a worse version would be to delete ``rubric_refs`` first.
    """
    new_digest = rubric_digest(new_schema)
    prev_digest = rubric_digest(prev_schema or {})
    if new_digest is None:
        if prev_digest is not None:
            return (
                "升版删掉了模板声明的尺子：没有尺子的模板永远无法证明自己没有变差，"
                "不接受以移除尺子换取的升版。"
            )
        return None  # neither version declares rulers — nothing to judge by
    latest = _latest_verdict(conn, template_name)
    if latest is None:
        return None  # no comparable history — this version establishes the baseline
    if latest.get("ruler_digest") and latest["ruler_digest"] != new_digest:
        return None  # measuring stick moved: also a baseline, not a regression
    outcome = latest.get("outcome")
    if outcome == "pass":
        return None
    if outcome == "inconclusive":
        return (
            "升版被判为「判不出来」（样本不足/尺子不可达/校验器未执行），"
            f"不放行。台账记录 id={latest.get('id')}。"
        )
    return f"升版会使模板变差：最近一条结论为 fail（台账记录 id={latest.get('id')}）。"


def promote_template_via_gate(
    conn: Any, *, name: str, schema: dict, created_by: str
) -> dict:
    """Append a new version only if it clears the novelty gate.

    Version 1 is always allowed: a first version has nothing to be worse than.
    """
    from . import templates

    existing = templates.get_template(conn, name=name)
    if existing is None:
        return templates.create_template(
            conn, name=name, schema=schema, created_by=created_by
        )
    problem = promotion_problem(
        conn, template_name=name, new_schema=schema, prev_schema=existing["schema"]
    )
    if problem:
        raise ValueError(problem)
    return templates.update_template(
        conn, name=name, schema=schema, created_by=created_by
    )
