"""Suggest retag node: LLM analyzes failing clauses and suggests tag changes.

This node is used in the tag_iteration pipeline to analyze clauses that caused
evaluation failures and suggest tag modifications (scenario, stance, strength, etc.)
that might improve future evaluations.

**Concurrency:** Safe to run in parallel (read-only on clauses table).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("LITELLM_MODEL_COST_MAP_URL", "")


def _build_prompt(
    contract_type: str,
    scenario: str | None,
    stance: str | None,
    failing: list[dict],
    clauses_with_tags: list[dict],
) -> str:
    """Build LLM prompt for tag suggestion."""
    fails = "\n".join(
        f"- [{c.get('verdict')}] {c.get('title', '')}：{(c.get('reasoning') or '')[:200]}"
        for c in failing
    ) or "（无）"

    clist = "\n".join(
        f"- id={c['id']} section={c.get('section')} tags={c.get('tags')} body={(c.get('body') or '')[:120]}"
        for c in clauses_with_tags
    ) or "（无条款）"

    return (
        "你是合同条款标签分析师。一份"
        f"{scenario or ''}{contract_type} 合同（stance={stance}）评估未全通过。挂掉的评审项：\n"
        f"{fails}\n\n"
        "当前使用的条款及其 tags：\n"
        f"{clist}\n\n"
        "请分析每个条款的 tags 是否合理：\n"
        "1. 条款内容涉及的业务场景 (scenario) 是否与 tag 匹配？\n"
        "2. 条款的利益倾向 (stance) 是否与合同要求一致？\n"
        "3. 条款的强度 (strength) 是否合适？\n"
        "4. 其他 tags (risk, mandatory 等) 是否合理？\n\n"
        "输出严格 JSON 数组：[{\"clause_id\": id, \"section\": \"...\", "
        "\"current_tags\": {...}, \"suggested_tags\": {...}, \"reason\": \"...\"}]\n"
        "只输出需要修改的条款。无修改建议则输出空数组 []。"
    )


def _call_llm(prompt: str, temperature: float = 0.0) -> str:
    """Call LLM for tag suggestion."""
    import litellm

    model = os.environ.get("PIPELINE_MODEL") or os.environ.get("DRAFTER_MODEL")
    if not model:
        raise RuntimeError("DRAFTER_MODEL is not set")
    resp = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=int(os.environ.get("IMPROVE_MAX_TOKENS", "2048")),
    )
    return resp.choices[0].message.content or ""


def _parse(raw: str) -> list[dict]:
    """Parse LLM response into suggestion list."""
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    # Try to extract JSON array
    if not text.startswith("["):
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]

    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        return []

    if not isinstance(data, list):
        return []

    # Validate each suggestion
    suggestions = []
    for s in data:
        if not isinstance(s, dict):
            continue
        if s.get("clause_id") is None:
            continue
        if not isinstance(s.get("suggested_tags"), dict):
            continue
        suggestions.append({
            "clause_id": int(s["clause_id"]),
            "section": s.get("section", ""),
            "current_tags": s.get("current_tags", {}),
            "suggested_tags": s["suggested_tags"],
            "reason": s.get("reason", ""),
        })
    return suggestions


def suggest_retag(
    contract_type: str,
    scenario: str | None,
    stance: str | None,
    failing_criteria: list[dict],
    clauses_with_tags: list[dict],
) -> list[dict]:
    """Suggest tag changes for failing clauses. Returns list of suggestions.

    Each suggestion: {clause_id, section, current_tags, suggested_tags, reason}
    Never raises - returns empty list on any error.
    """
    if not failing_criteria or not clauses_with_tags:
        return []
    try:
        return _parse(_call_llm(_build_prompt(contract_type, scenario, stance, failing_criteria, clauses_with_tags)))
    except Exception:  # noqa: BLE001 - never crash the pipeline
        return []


def suggest_retag_node(state: dict) -> dict:
    """LangGraph node: analyze failing clauses and suggest tag changes."""
    from .graph import _current_customs

    contract_type = state["contract_type"]
    stance = state.get("stance")
    scenario = (state.get("tags") or {}).get("scenario")

    # Get failing criteria from evaluation
    failing = [
        c for c in state["eval_result"].get("criteria_results", [])
        if c.get("verdict") != "pass"
    ]

    # Get current custom clauses with their tags
    customs = _current_customs(contract_type, stance)

    # Call LLM to suggest tag changes
    suggestions = suggest_retag(
        contract_type,
        scenario,
        stance,
        failing,
        customs,
    )

    return {"retag_suggestions": suggestions}
