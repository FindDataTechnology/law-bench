"""Unit tests for ``src/eval/judge.py``."""

from __future__ import annotations

import pytest

from src.eval.judge import _strip_litellm_prefix, get_judge


def test_strip_litellm_prefix_removes_openai_prefix():
    assert _strip_litellm_prefix("openai/glm-5.2") == "glm-5.2"


def test_strip_litellm_prefix_passthrough_without_prefix():
    assert _strip_litellm_prefix("glm-5.2") == "glm-5.2"
    assert _strip_litellm_prefix("deepseek-v4") == "deepseek-v4"


def test_get_judge_raises_on_missing_env(monkeypatch):
    for v in ("OPENAI_API_KEY", "OPENAI_API_BASE", "EVAL_MODEL"):
        monkeypatch.delenv(v, raising=False)
    with pytest.raises(RuntimeError, match="Missing env vars"):
        get_judge()


def test_get_judge_raises_when_env_partial(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    monkeypatch.setenv("EVAL_MODEL", "openai/glm-5.2")
    with pytest.raises(RuntimeError):
        get_judge()
