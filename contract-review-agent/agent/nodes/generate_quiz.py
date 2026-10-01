"""generate_quiz node — turn every slot into a natural-language question.

For each ``{{slot}}`` found in the assembled draft, use QUIZ_MODEL to generate
a human-readable question that incorporates the slot's instruction (label,
description, example) so the human knows exactly what to fill in. Every slot is
marked required=True — the frontend blocks submit until all are filled.

The question is generated in one LLM call for all slots (cheaper than one call
per slot) and parsed from a JSON mapping.
"""
from __future__ import annotations

import json
import time

from langchain_core.runnables import RunnableConfig

from ..config import quiz_model
from ..state import ReviewState
from .llm import call_llm


_QUIZ_SYSTEM = """你是合同填槽助手。给定一个槽位列表（含名称、标签、说明、示例），为每个槽位生成一句自然语言提问，帮助用户填入真实值。
要求：
- 提问要具体、贴合合同场景，必要时给出单位或格式提示（金额、日期 YYYY-MM-DD、地址等）。
- 不要给选项，让用户自由填写。
只输出严格 JSON：{"槽位名": "提问句"}，不要任何解释。"""


def _build_user(instructions: list[dict]) -> str:
    lines = []
    for i in instructions:
        lines.append(
            f"- 槽位：{i.get('name')}｜标签：{i.get('label') or i.get('name')}"
            f"｜说明：{i.get('description') or ''}｜示例：{i.get('example') or ''}"
        )
    return "请为以下每个槽位生成一句提问：\n" + "\n".join(lines)


def _parse_questions(text: str) -> dict[str, str]:
    if not text:
        return {}
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if isinstance(v, str)}
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(text[start : end + 1])
                if isinstance(data, dict):
                    return {k: v for k, v in data.items() if isinstance(v, str)}
            except json.JSONDecodeError:
                pass
    return {}


def generate_quiz_node(state: ReviewState, config: RunnableConfig) -> dict:
    """Generate a question per slot; every slot is required."""
    t0 = time.perf_counter()
    slots = state.get("slots") or []
    instructions = state.get("instructions") or []
    instr_by_name = {i.get("name"): i for i in instructions if i.get("name")}
    errors = list(state.get("errors") or [])
    model_calls = list(state.get("model_calls") or [])

    questions: dict[str, str] = {}
    if slots:
        instrs = [instr_by_name.get(s, {"name": s}) for s in slots]
        try:
            res = call_llm_sync(model=quiz_model(), instructions=instrs)
            questions = res.get("questions", {})
            model_calls.append({
                "model": quiz_model(),
                "node": "generate_quiz",
                "tokens": res.get("tokens", 0),
                "cost": res.get("cost", 0.0),
                "latency_seconds": res.get("latency", 0.0),
            })
            if res.get("error"):
                errors.append({"node": "generate_quiz", "message": res["error"]})
        except Exception as exc:  # noqa: BLE001
            errors.append({"node": "generate_quiz", "message": str(exc)})

    # Fallback question if the LLM didn't produce one for a slot.
    quiz_items = []
    for s in slots:
        instr = instr_by_name.get(s, {})
        question = questions.get(s) or f"请填写{s}（{(instr.get('label') or s)}）：{instr.get('description') or ''}"
        quiz_items.append({
            "slot": s,
            "question": question,
            "required": True,
            "label": instr.get("label") or s,
            "description": instr.get("description") or "",
            "example": instr.get("example") or "",
        })

    elapsed = time.perf_counter() - t0
    return {
        "quiz_items": quiz_items,
        "current_stage": "generate_quiz",
        "model_calls": model_calls,
        "node_timings": {**(state.get("node_timings") or {}),
                         "generate_quiz": round(elapsed, 3)},
        "errors": errors,
    }


def call_llm_sync(model: str, instructions: list[dict]) -> dict:
    """Sync wrapper around the async call_llm (quiz node is sync)."""
    import asyncio

    from .llm import call_llm

    user = _build_user(instructions)
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If we're inside a running loop, run in a fresh loop.
            new_loop = asyncio.new_event_loop()
            try:
                res = new_loop.run_until_complete(
                    call_llm(model=model, system=_QUIZ_SYSTEM, user=user)
                )
            finally:
                new_loop.close()
        else:
            res = loop.run_until_complete(
                call_llm(model=model, system=_QUIZ_SYSTEM, user=user)
            )
    except RuntimeError:
        res = asyncio.run(call_llm(model=model, system=_QUIZ_SYSTEM, user=user))

    return {
        "questions": _parse_questions(res.get("text") or ""),
        "tokens": res.get("tokens", 0),
        "cost": res.get("cost", 0.0),
        "latency": res.get("latency", 0.0),
        "error": res.get("error"),
    }
