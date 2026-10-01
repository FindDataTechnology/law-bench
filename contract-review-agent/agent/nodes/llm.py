"""Shared LLM call helper for review-agent nodes.

Uses litellm (already a dependency via the law-bench venv) pointed at the
OpenAI-compatible relay. Returns the text, token usage, and latency so each
node can record per-model metrics for the agent_runs table.

All nodes go through ``call_llm`` so model-call accounting is centralized.

Rate-limit resilience: the relay (www.linjie.love) is a shared service with a
low concurrency cap (~4) that is often saturated by other consumers ("没有可
分配的空闲 PAT"). ``call_llm`` retries rate-limit / concurrency / quota /
transient errors with backoff so a transient throttle doesn't drop a reviewer.
Config:
- LLM_MAX_RETRIES: retries on rate-limit/429/quota/5xx (default 4).
- LLM_RETRY_BACKOFF: base seconds between retries (default 2).
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from dotenv import load_dotenv

load_dotenv()
# litellm fetches a remote model-cost-map on first call; force local fallback.
os.environ.setdefault("LITELLM_MODEL_COST_MAP_URL", "")


def _max_retries() -> int:
    try:
        return max(0, int(os.environ.get("LLM_MAX_RETRIES", "4")))
    except (TypeError, ValueError):
        return 4


def _retry_backoff() -> float:
    try:
        return max(0.0, float(os.environ.get("LLM_RETRY_BACKOFF", "2")))
    except (TypeError, ValueError):
        return 2.0


def _is_retryable(exc: Exception) -> bool:
    """True for rate-limit / concurrency / quota / transient network errors."""
    msg = str(exc).lower()
    markers = (
        "ratelimit",
        "rate limit",
        "too many",
        "429",
        "并发请求过多",
        "concurrency",
        "serviceunavailable",
        "service unavailable",
        "没有可分配的空闲",
        "空闲 pat",
        "quota",
        "配额",
        "connection reset",
        "timeout",
        "temporarily",
        "overloaded",
        "busy",
        "502",
        "503",
    )
    return any(m in msg for m in markers)


async def _acompletion_with_retry(
    litellm: Any, kwargs: dict[str, Any]
) -> Any:
    """Call litellm.acompletion with retry on rate-limit errors."""
    max_retries = _max_retries()
    backoff = _retry_backoff()
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await litellm.acompletion(**kwargs)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= max_retries or not _is_retryable(exc):
                raise
            wait = backoff * (attempt + 1)
            if os.environ.get("DEBUG"):
                print(f"[call_llm] retry {attempt+1}/{max_retries} after {wait:.1f}s: {exc}")
            await asyncio.sleep(wait)
    raise last_exc  # pragma: no cover - loop always returns or raises


async def call_llm(
    model: str,
    system: str,
    user: str,
    temperature: float = 0.0,
    max_tokens: int | None = None,
) -> dict:
    """Call the relay via litellm and return {text, tokens, cost, latency}.

    Robust: on any LLM/parse failure returns ``{error, text: "", tokens: 0}``
    so a node never crashes the graph — it just records an error. Rate-limit /
    concurrency errors are retried with backoff (see module docstring).
    """
    import litellm

    t0 = time.perf_counter()
    try:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        resp = await _acompletion_with_retry(litellm, kwargs)
        text = (resp.choices[0].message.content or "").strip()
        usage = getattr(resp, "usage", None)
        tokens = int(getattr(usage, "total_tokens", 0) or 0)
        # The relay rewrites ``resp.model`` to upstream ids (gm51model, qmodel,
        # auto, kmodel_latest) that litellm's cost map doesn't know; guard the
        # pricing call so an unmapped model yields cost=0.0 instead of
        # discarding a successful completion as an error.
        try:
            cost = float(
                litellm.completion_cost(completion_response=resp)
                if _cost_available(resp)
                else 0.0
            )
        except Exception:
            cost = 0.0
        latency = time.perf_counter() - t0
        return {"text": text, "tokens": tokens, "cost": cost, "latency": latency}
    except Exception as exc:  # noqa: BLE001
        return {
            "text": "",
            "tokens": 0,
            "cost": 0.0,
            "latency": time.perf_counter() - t0,
            "error": str(exc),
        }


def _cost_available(resp: Any) -> bool:
    """litellm.completion_cost raises if it can't price the model; guard it."""
    try:
        return bool(getattr(resp, "model", ""))
    except Exception:
        return False
