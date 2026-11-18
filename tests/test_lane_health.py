"""Model-lane health (§ the 2026-11-09 outage).

On 2026-11-09 the shared model lane returned `400 InvalidSubscription` while
`eval_runs` was empty — the evaluation area had never worked and nothing said
so. These tests pin the two answers that must stay distinct:

- configuration (cheap, always accurate, never claims "broken");
- a probe (one explicit call, reports the upstream's own words).
"""

from __future__ import annotations

import httpx
import pytest

from src.bench import lane


class _Resp:
    def __init__(self, status: int, text: str = ""):
        self.status_code = status
        self.text = text


def test_describe_reports_missing_pieces_not_failure():
    state = lane.describe({"OPENAI_API_BASE": "https://x/v1"})
    assert state["configured"] is False
    assert state["missing"] == ["key", "model"]
    assert state["base"] == "https://x/v1"


def test_describe_strips_the_litellm_prefix():
    state = lane.describe({
        "OPENAI_API_BASE": "https://x/v1", "OPENAI_API_KEY": "k",
        "EVAL_MODEL": "openai/deepseek-v4-flash",
    })
    assert state["configured"] is True
    assert state["model"] == "deepseek-v4-flash"


def test_describe_falls_back_to_openrouter_names():
    state = lane.describe({
        "OPENROUTER_API_BASE": "https://r/v1", "OPENROUTER_API_KEY": "k",
        "EXTRACT_MODEL": "some/model",
    })
    assert state["configured"] is True and state["model"] == "some/model"


def test_probe_on_unconfigured_lane_does_not_call_out(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("must not call a lane that is not configured")
    monkeypatch.setattr(lane, "_probe_post", boom)
    result = lane.probe({})
    assert result["ok"] is False and "未配置" in result["detail"]


def test_probe_reports_the_upstream_error_verbatim(monkeypatch):
    monkeypatch.setattr(lane, "_probe_post", lambda *a, **kw: _Resp(
        400, '{"error":{"code":"InvalidSubscription"}}'))
    result = lane.probe({
        "OPENAI_API_BASE": "https://x/v1", "OPENAI_API_KEY": "k",
        "EVAL_MODEL": "openai/m",
    })
    assert result["ok"] is False
    assert result["status"] == 400
    assert "InvalidSubscription" in result["detail"]


def test_probe_success(monkeypatch):
    monkeypatch.setattr(lane, "_probe_post", lambda *a, **kw: _Resp(200))
    result = lane.probe({
        "OPENAI_API_BASE": "https://x/v1", "OPENAI_API_KEY": "k",
        "EVAL_MODEL": "openai/m",
    })
    assert result == {"ok": True, "status": 200, "detail": "", "model": "m"}


def test_probe_transport_failure_is_a_result_not_an_exception(monkeypatch):
    def boom(*a, **kw):
        raise httpx.ConnectError("no route")
    monkeypatch.setattr(lane, "_probe_post", boom)
    result = lane.probe({
        "OPENAI_API_BASE": "https://x/v1", "OPENAI_API_KEY": "k",
        "EVAL_MODEL": "openai/m",
    })
    assert result["ok"] is False and "ConnectError" in result["detail"]
