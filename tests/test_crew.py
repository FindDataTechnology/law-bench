"""Unit tests for ``src/crew.py``: template loading and crew assembly (no kickoff).

Crew assembly exercises the ``@agent`` methods (which call ``get_llm``), so the
per-role model env vars are set; no LLM kickoff is performed.
"""

from __future__ import annotations

from src.crew import ContractDraftingCrew, _templates_reference
from src.settings import TEMPLATES_DIR


def test_templates_reference_loads_seed_templates():
    ref = _templates_reference()
    assert ref  # non-empty
    # one block per templates/*.md
    expected_stems = sorted(p.stem for p in TEMPLATES_DIR.glob("*.md"))
    assert expected_stems  # templates exist in the repo
    for stem in expected_stems:
        assert f"### 模板：{stem}" in ref


def test_templates_reference_empty_when_no_templates(tmp_path, monkeypatch):
    monkeypatch.setattr("src.crew.TEMPLATES_DIR", tmp_path)
    assert _templates_reference() == ""


def test_crew_assembles_agents_and_tasks(monkeypatch):
    # the @agent methods call get_llm, which needs the per-role model env vars
    monkeypatch.setenv("INTAKE_MODEL", "openai/deepseek-v4-flash")
    monkeypatch.setenv("DRAFTER_MODEL", "openai/glm-5.2")
    monkeypatch.setenv("AUDITOR_MODEL", "openai/glm-5.2")
    crew = ContractDraftingCrew().crew()
    assert len(crew.agents) == 3
    assert len(crew.tasks) == 4
