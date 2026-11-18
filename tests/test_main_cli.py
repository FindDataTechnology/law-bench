"""CLI tests for ``main.py`` (no real LLM kickoff).

The crew kickoff is replaced with a fake, and ``load_dotenv`` is neutralized so
the real ``.env`` does not interfere with the env-var checks under test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import main as main_mod


def _set_env(monkeypatch):
    monkeypatch.setattr(main_mod, "load_dotenv", lambda: None)
    for v in (
        "OPENAI_API_KEY",
        "OPENAI_API_BASE",
        "INTAKE_MODEL",
        "DRAFTER_MODEL",
        "AUDITOR_MODEL",
    ):
        monkeypatch.setenv(v, "x")


class _FakeResult:
    raw = "起草的合同草案正文"


class _FakeCrew:
    """Stand-in for ContractDraftingCrew whose kickoff returns fixed text."""

    def crew(self):
        class _C:
            def kickoff(self, inputs):
                assert "user_request" in inputs
                return _FakeResult()

        return _C()


def test_writes_output_file(monkeypatch, tmp_path: Path):
    _set_env(monkeypatch)
    monkeypatch.setattr(main_mod, "ContractDraftingCrew", _FakeCrew)
    out = tmp_path / "out.md"
    rc = main_mod.main(["起草一份服务协议", str(out)])
    assert rc == 0
    assert out.read_text(encoding="utf-8") == "起草的合同草案正文"


def test_no_output_file_prints_result(monkeypatch, capsys):
    _set_env(monkeypatch)
    monkeypatch.setattr(main_mod, "ContractDraftingCrew", _FakeCrew)
    rc = main_mod.main(["起草一份服务协议"])
    assert rc == 0
    assert "起草的合同草案正文" in capsys.readouterr().out


def test_missing_args_errors(monkeypatch):
    _set_env(monkeypatch)
    with pytest.raises(SystemExit):
        main_mod.main([])


def test_missing_env_returns_error(monkeypatch):
    monkeypatch.setattr(main_mod, "load_dotenv", lambda: None)
    for v in (
        "OPENAI_API_KEY",
        "OPENAI_API_BASE",
        "INTAKE_MODEL",
        "DRAFTER_MODEL",
        "AUDITOR_MODEL",
    ):
        monkeypatch.delenv(v, raising=False)
    rc = main_mod.main(["起草一份服务协议"])
    assert rc == 1
