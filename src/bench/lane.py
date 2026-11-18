"""Model-lane health: is the thing that answers questions actually there?

Both the evaluation judge and ontology extraction call one OpenAI-compatible
endpoint. When that lane is dead the symptoms are quiet and misleading: no runs
appear, the estate matrix says "no evaluation yet", and an operator dispatches a
task to write standards that already exist. On 2026-11-09 the lane returned
``400 InvalidSubscription`` (expired AgentPlus plan) while ``eval_runs`` was
empty — nobody had ever seen it work.

So this module answers two different questions and keeps them apart:

- :func:`describe` — **configuration only**. Cheap, always accurate, no network.
  "Not configured" is a fact; it never claims "broken".
- :func:`probe` — **one explicit call**. Only ever run because a human asked, so
  a dead upstream costs one request and yields its own error message instead of
  a page that hangs or a page that lies.

Nothing here writes, caches, or retries. A probe result is shown once and
discarded: a stored "last known good" would be the next lie in this chain.
"""

from __future__ import annotations

import os
from typing import Optional

import httpx

#: Config names, in the order the failure message should name them.
_BASE_VARS = ("OPENAI_API_BASE", "OPENROUTER_API_BASE")
_KEY_VARS = ("OPENAI_API_KEY", "OPENROUTER_API_KEY")
_MODEL_VARS = ("EVAL_MODEL", "EXTRACT_MODEL")

_probe_post = httpx.post  # test seam


def _first(env: dict, names: tuple[str, ...]) -> Optional[str]:
    for name in names:
        value = (env.get(name) or "").strip()
        if value:
            return value
    return None


def _model_name(model: str) -> str:
    """Strip the litellm ``openai/`` prefix the OpenAI SDK does not understand."""
    return model.split("/", 1)[1] if model.startswith("openai/") else model


def describe(env: Optional[dict] = None) -> dict:
    """Configuration state of the lane. Pure, no network, no side effects."""
    source = dict(os.environ if env is None else env)
    base = _first(source, _BASE_VARS)
    key = _first(source, _KEY_VARS)
    model = _first(source, _MODEL_VARS)
    missing = [
        label
        for label, value in (
            ("base", base), ("key", key), ("model", model),
        )
        if not value
    ]
    return {
        "configured": not missing,
        "base": base,
        "model": _model_name(model) if model else None,
        "missing": missing,
    }


def probe(env: Optional[dict] = None, *, timeout: float = 30.0) -> dict:
    """Make one real call and report what came back.

    Returns ``{"ok", "status", "detail", "model"}``. An HTTP error is a *result*
    here, not an exception: the point of the probe is to show the upstream's own
    words (``InvalidSubscription`` is far more actionable than "probe failed").
    """
    state = describe(env)
    if not state["configured"]:
        return {
            "ok": False,
            "status": None,
            "detail": f"未配置：缺少 {', '.join(state['missing'])}",
            "model": state["model"],
        }
    source = dict(os.environ if env is None else env)
    try:
        resp = _probe_post(
            f"{state['base'].rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {_first(source, _KEY_VARS)}"},
            json={
                "model": state["model"],
                "temperature": 0.0,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 8,
            },
            timeout=timeout,
        )
    except Exception as exc:  # transport failure: name it, don't hide it
        return {
            "ok": False,
            "status": None,
            "detail": f"{type(exc).__name__}: {exc}",
            "model": state["model"],
        }
    if resp.status_code == 200:
        return {"ok": True, "status": 200, "detail": "", "model": state["model"]}
    return {
        "ok": False,
        "status": resp.status_code,
        "detail": (resp.text or "").strip()[:400],
        "model": state["model"],
    }
