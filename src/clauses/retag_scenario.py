"""One-time retag: assign ``tags.scenario`` (业务场景) to existing clauses.

Replaces the retired province ``region`` dimension. The extraction LLM is run
in a *classify-only* mode over each clause body (no re-extraction): given the
clause body + the contract type's seeded scenario vocab, it suggests a scenario
label. The suggestion is written to ``tags.scenario`` and
``tag_review.scenario`` is set to ``pending`` (assembly ignores pending), so a
human can bulk-approve per type on the review dashboard.

Runbook (deploy):
  1. ``python -m src.clauses retag-scenario --limit 5``   # smoke a few
  2. ``python -m src.clauses retag-scenario``              # full run
  3. Bulk-approve per type on /clauses/review (or ``bulk_review``).

The region->scenario JSONB cleanup (``tags - 'region'``, ``tag_review - 'region'``)
runs automatically in :func:`src.eval.store.ensure_schema`; this script only
*adds* ``scenario``. Clauses the LLM can't classify are left without a scenario
(pending human entry).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from dotenv import load_dotenv
from psycopg.types.json import Jsonb

load_dotenv()
os.environ.setdefault("LITELLM_MODEL_COST_MAP_URL", "")

from src.eval.db import connect
from src.eval.store import ensure_schema

from .scenario_vocab import SCENARIO_VOCAB
from .tags import TAG_VOCAB

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _scenario_vocab(contract_type: str) -> list[str]:
    """Merged scenario vocab for a type: seeded + any DB-loaded values."""
    seeded = SCENARIO_VOCAB.get(contract_type, [])
    loaded = TAG_VOCAB.get(contract_type, {}).get("scenario", [])
    seen: list[str] = []
    for v in list(seeded) + list(loaded):
        if v and v not in seen:
            seen.append(v)
    return seen


def _build_prompt(body: str, contract_type: str, vocab: list[str]) -> str:
    vocab_str = "、".join(vocab) if vocab else "（无预设清单，自行判断合适的简短中文标签）"
    return (
        "你是中国合同条款分类助手。判断下面这条合同条款所属的**业务场景/交易子类型**，"
        "用简短中文标签回答（如 农产品买卖、消费品零售、驾校培训、养老服务、住宅租赁、建设工程、快递 等）。\n\n"
        f"该合同类型（{contract_type}）的候选场景清单：{vocab_str}。\n"
        "若条款明确属于清单中某项，输出该项；否则输出一个最贴切的简短中文标签。"
        "只输出标签文本本身，不要解释、不要引号、不要标点。\n\n"
        f"条款正文：\n{body[:800]}"
    )


def _call_llm(prompt: str) -> str:
    import litellm

    model = os.environ.get("DRAFTER_MODEL")
    if not model:
        raise RuntimeError("DRAFTER_MODEL is not set")
    resp = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=64,
    )
    return (resp.choices[0].message.content or "").strip()


def _classify(body: str, contract_type: str) -> str | None:
    vocab = _scenario_vocab(contract_type)
    raw = _call_llm(_build_prompt(body, contract_type, vocab))
    # tolerate a fenced/quoted reply; take the first non-empty line.
    fence = _JSON_FENCE_RE.search(raw)
    if fence:
        raw = fence.group(1).strip()
    raw = raw.strip().strip('"“”').splitlines()[0].strip() if raw else ""
    return raw[:32] or None


def retag_scenarios(
    contract_type: str | None = None,
    *,
    limit: int | None = None,
    db: Any = None,
) -> dict:
    """Assign ``tags.scenario`` (pending) to clauses missing one.

    Targets ``source='tagged'`` clauses (the regional 示范文本 corpus) by
    default across all types, or one ``contract_type`` if given. Returns
    ``{classified, skipped, failed}``. Writes ``tags.scenario`` +
    ``tag_review.scenario='pending'`` via a direct SQL update (does not mark
    clauses ``manual``).
    """
    ensure_schema(db)
    conn = connect(db)
    try:
        where = ["tags->>'source' = 'tagged'"]
        params: list = []
        if contract_type:
            where.append("contract_type = %s")
            params.append(contract_type)
        where.append("(tags ? 'scenario') IS NOT TRUE")  # missing scenario
        sql = (
            "SELECT id, contract_type, body FROM clauses WHERE "
            + " AND ".join(where)
            + " ORDER BY id"
        )
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = conn.execute(sql, params).fetchall()
    finally:
        if db is None:
            conn.close()

    classified = skipped = failed = 0
    conn = connect(db)
    try:
        for r in rows:
            body = (r["body"] or "").strip()
            if not body:
                skipped += 1
                continue
            try:
                scenario = _classify(body, r["contract_type"])
            except Exception:  # noqa: BLE001 - isolate per-clause LLM failures
                failed += 1
                continue
            if not scenario:
                skipped += 1
                continue
            conn.execute(
                "UPDATE clauses SET "
                "tags = tags || jsonb_build_object('scenario', %s::text), "
                "tag_review = tag_review || jsonb_build_object('scenario', 'pending') "
                "WHERE id = %s",
                (scenario, r["id"]),
            )
            classified += 1
        conn.commit()
    finally:
        if db is None:
            conn.close()
    return {"classified": classified, "skipped": skipped, "failed": failed}
