"""Self-healing ``improve`` node: LLM diagnosis of a failing eval.

Given the failing criteria + the custom clauses currently in play (which may be
thin overrides of a rich base), an LLM emits:
- ``exclude_custom_clause_ids``: ids to drop from the next ``generate`` call (per-run,
  via ``custom_clause_ids``) so the rich base can win - **the shared clauses table
  is never mutated by the loop**.
- ``recommendations``: ``clause_review`` actions recorded on the pipeline row for a
  human to apply later - **never executed by the loop**.

Robust: any LLM / parse failure yields empty actions so the loop never crashes; it
just re-runs until ``max_iterations``.
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
    customs: list[dict],
) -> str:
    fails = "\n".join(
        f"- [{c.get('verdict')}] {c.get('title', '')}：{(c.get('reasoning') or '')[:200]}"
        for c in failing
    ) or "（无）"
    clist = "\n".join(
        f"- id={c['id']} section={c.get('section')} body={(c.get('body') or '')[:120]}"
        for c in customs
    ) or "（无 custom 条款命中）"
    return (
        "你是合同自愈诊断助手。一份"
        f"{scenario or ''}{contract_type} 合同（stance={stance}）评估未全通过。挂掉的评审项：\n"
        f"{fails}\n\n"
        "当前 stance 命中、装配可用的 custom 条款（可能盖掉更丰富的 base）：\n"
        f"{clist}\n\n"
        "请判断：\n"
        "1. exclude_custom_clause_ids：本轮应排除哪些 custom 条款（不选入装配），让富 base 接管该 section？给 id 列表。\n"
        "2. recommendations：哪些 custom 条款建议全局 reject（供人复核后 clause_review）？给 "
        '[{"clause_id": id, "action": "reject", "reason": "..."}]。\n\n'
        "只输出严格 JSON：{\"exclude_custom_clause_ids\": [id,...], "
        '"recommendations": [{"clause_id": id, "action": "reject", "reason": "..."}]}，'
        "不要解释；无动作则输出空列表。"
    )


def _call_llm(prompt: str, temperature: float = 0.0) -> str:
    import litellm

    model = os.environ.get("PIPELINE_MODEL") or os.environ.get("DRAFTER_MODEL")
    if not model:
        raise RuntimeError("DRAFTER_MODEL is not set")
    resp = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=int(os.environ.get("IMPROVE_MAX_TOKENS", "1024")),
    )
    return resp.choices[0].message.content or ""


def _parse(raw: str) -> dict:
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        return {"exclude_custom_clause_ids": [], "recommendations": []}
    if not isinstance(data, dict):
        return {"exclude_custom_clause_ids": [], "recommendations": []}
    excl = data.get("exclude_custom_clause_ids") or []
    excl = [int(x) for x in excl if str(x).strip().lstrip("-").isdigit()] if isinstance(excl, list) else []
    recs = data.get("recommendations") or []
    recs = [r for r in recs if isinstance(r, dict) and r.get("clause_id") is not None] if isinstance(recs, list) else []
    return {"exclude_custom_clause_ids": excl, "recommendations": recs}


def diagnose(
    contract_type: str,
    scenario: str | None,
    stance: str | None,
    failing_criteria: list[dict],
    customs: list[dict],
) -> dict:
    """Return ``{exclude_custom_clause_ids, recommendations}``; never raises."""
    if not failing_criteria or not customs:
        return {"exclude_custom_clause_ids": [], "recommendations": []}
    try:
        return _parse(_call_llm(_build_prompt(contract_type, scenario, stance, failing_criteria, customs)))
    except Exception:  # noqa: BLE001 - never crash the loop
        return {"exclude_custom_clause_ids": [], "recommendations": []}
