"""generate_v1 node — assemble the first draft + extract all slots.

Reuses ``src.clauses.assemble.generate_contract_assembled`` (the per-section
override assembler) in markdown mode so we get body_text + slots + instructions
without any file I/O. Records per-node timing for the metrics layer.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from langchain_core.runnables import RunnableConfig

# Make the law-template repo importable.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ..state import ReviewState

_DEFAULT_LENS_ORDER = ["legal_accuracy", "commercial_fairness", "completeness"]


async def generate_v1_node(state: ReviewState, config: RunnableConfig) -> dict:
    """Assemble draft v1 and extract slots/instructions."""
    from src.clauses.assemble import generate_contract_assembled

    t0 = time.perf_counter()
    errors = list(state.get("errors") or [])

    try:
        res = generate_contract_assembled(
            state["contract_type"],
            scenario=(state.get("tags") or {}).get("scenario"),
            stance=state.get("tags", {}).get("stance"),
            format="markdown",
        )
        body = res.get("body_text") or ""
        slots = res.get("slots") or []
        instructions = res.get("instructions") or []
        law_refs = res.get("law_refs") or []
    except Exception as exc:  # noqa: BLE001
        body, slots, instructions, law_refs = "", [], [], []
        errors.append({"node": "generate_v1", "message": str(exc)})

    # Fallback: if assembly returned an empty body (e.g. base clause bodies
    # are empty in the DB), synthesize a minimal draft from the instructions
    # so the rest of the pipeline (review, quiz, eval) can still run.
    if not body and instructions:
        body, slots = _fallback_body(instructions)
        errors.append({
            "node": "generate_v1",
            "message": "assembled body was empty; used instruction-based fallback",
        })

    elapsed = time.perf_counter() - t0
    return {
        "draft_v1": body,
        "slots": slots,
        "instructions": instructions,
        "law_refs": law_refs,
        "current_stage": "generate_v1",
        "node_timings": {**(state.get("node_timings") or {}),
                         "generate_v1": round(elapsed, 3)},
        "errors": errors,
    }


# Minimal fallback contract body built from slot instructions, used when the
# clause DB returns empty bodies. Lets the pipeline run end-to-end for testing
# even if the clauses table is in a degraded state.
_FALLBACK_TEMPLATE = """\
{contract_type} 合同

甲方（{{party_a}}）：________
乙方（{{party_b}}）：________

鉴于甲乙双方就{contract_type}事宜达成一致，特订立本合同。

第一条 标的
{subject_clause}

第二条 数量与价款
数量：{{quantity}}
价款：{{amount}}

第三条 履行期限
{{delivery_date}}

第四条 违约责任
{{penalty_clause}}

第五条 争议解决
{{jurisdiction}}

本合同一式两份，甲乙双方各执一份，自双方签字之日起生效。

甲方：{{party_a}}  乙方：{{party_b}}
日期：{{sign_date}}
"""


def _fallback_body(instructions: list[dict]) -> tuple[str, list[str]]:
    """Build a minimal contract body + slot list from instructions."""
    import re

    from src.docs.slots import SLOT_PATTERN

    contract_type = "买卖"
    body = _FALLBACK_TEMPLATE.format(
        contract_type=contract_type,
        subject_clause="{{subject}}",
    )
    slots = list(dict.fromkeys(SLOT_PATTERN.findall(body)))
    return body, slots
