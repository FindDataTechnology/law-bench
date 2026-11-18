"""LLM slot-fill node + ``fill_cache`` memoization.

Fills **every** ``{{slot}}`` in the assembled body with a scenario-aware value via
the ``DRAFTER_MODEL`` (litellm, mirroring :mod:`src.clauses.extract`). Results are
cached in ``fill_cache`` keyed by ``(contract_type, scenario, sorted(slots),
model, temperature)`` so identical inputs are deterministic and amortize the LLM
cost; ``temperature`` + ``model`` are recorded. ``temperature`` defaults to 0.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

from dotenv import load_dotenv

load_dotenv()
# Avoid litellm's remote model-cost-map fetch (network-dependent); local fallback.
os.environ.setdefault("LITELLM_MODEL_COST_MAP_URL", "")

from src.docs import SLOT_PATTERN  # matches {{slot}}
from src.eval.pipeline_store import insert_fill, lookup_fill

_SLOT_NAME = re.compile(r"\{\{(\w+)\}\}")


def _cache_key(
    contract_type: str,
    scenario: str | None,
    slots: list[str],
    model: str | None,
    temperature: float,
    task_desc: str | None,
) -> tuple[str, str]:
    slots_sorted = ",".join(sorted(slots))
    raw = f"{contract_type}|{scenario}|{slots_sorted}|{model}|{temperature}|{task_desc or ''}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest(), hashlib.sha1(slots_sorted.encode("utf-8")).hexdigest()


def _build_prompt(
    contract_type: str, scenario: str | None, instructions: list[dict], task_desc: str | None
) -> str:
    lines = "\n".join(
        f"- {i['name']}（{i.get('label') or i['name']}）：{i.get('description') or ''} 示例：{i.get('example') or ''}"
        for i in instructions
    )
    ctx = f"{scenario}场景下的" if scenario else ""
    task_line = f"\n\n起草需求（subject 等槽值必须符合此需求，如指定了标的就用指定标的）：\n{task_desc}" if task_desc else ""
    return (
        "你是合同填槽助手。请为一份"
        f"{ctx}{contract_type} 合同生成真实、合理、互相一致的槽值（甲方/乙方名称、标的、金额、日期、"
        "违约金、管辖等）。槽清单：\n"
        f"{lines}{task_line}\n\n"
        "要求：每个槽都要填一个具体值（不要保留占位符）；金额用数字；日期用 YYYY-MM-DD；"
        "标的要贴合场景与起草需求。仅输出严格 JSON：{\"slot名\": \"值\"}，不要任何解释。"
    )


def _call_llm(prompt: str, temperature: float) -> tuple[str, str | None]:
    import litellm

    model = os.environ.get("DRAFTER_MODEL")
    if not model:
        raise RuntimeError("DRAFTER_MODEL is not set")
    resp = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=int(os.environ.get("FILL_MAX_TOKENS", "1024")),
    )
    return resp.choices[0].message.content or "", model


def _parse_json(raw: str) -> dict:
    """Parse the LLM's JSON, tolerating a code fence / surrounding prose."""
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
    except Exception:  # noqa: BLE001 - bad LLM output -> empty fill
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def fill_slots(
    contract_type: str,
    scenario: str | None,
    slots: list[str],
    instructions: list[dict],
    temperature: float = 0.0,
    task_desc: str | None = None,
) -> dict:
    """Return ``{fill_values, fill_cache_id, hit, model, temperature}``.

    On a cache hit the LLM is skipped. ``instructions`` is the slot-instruction
    manifest (``{name, label, description, example, required}``); only slots in
    ``slots`` are kept from the LLM output. ``task_desc`` (the drafting request)
    grounds the fill so e.g. the subject matches a requested 标的.
    """
    model = os.environ.get("DRAFTER_MODEL")
    cache_key, slots_hash = _cache_key(contract_type, scenario, slots, model, temperature, task_desc)
    cached = lookup_fill(cache_key)
    if cached is not None:
        return {
            "fill_values": cached["fill_values"],
            "fill_cache_id": cached["id"],
            "hit": True,
            "model": cached.get("model"),
            "temperature": cached.get("temperature"),
        }

    raw, model = _call_llm(_build_prompt(contract_type, scenario, instructions, task_desc), temperature)
    values = {k: v for k, v in _parse_json(raw).items() if k in slots}
    cache_id = insert_fill(cache_key, contract_type, scenario, slots_hash, values, temperature, model)
    return {"fill_values": values, "fill_cache_id": cache_id, "hit": False, "model": model, "temperature": temperature}


def render_filled(body_text: str, fill_values: dict[str, Any]) -> tuple[str, list[str]]:
    """Substitute ``{{slot}}`` -> value; return (filled_text, unfilled_slot_names)."""
    unfilled: list[str] = []

    def _repl(m: "re.Match[str]") -> str:
        name = m.group(1)
        v = fill_values.get(name)
        if v is None or v == "":
            unfilled.append(name)
            return m.group(0)
        return str(v)

    filled = SLOT_PATTERN.sub(_repl, body_text or "")
    return filled, unfilled
