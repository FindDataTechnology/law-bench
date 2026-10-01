"""CLI tests for ``src/eval/run.py`` (no real LLM calls).

``evaluate_contract`` is monkeypatched for the scoring path, and the
``list_rubrics`` / ``list_runs`` / ``store_result`` helpers are pointed at the
throwaway seeded DB so the development database is never touched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from src.eval import rubric, run as run_mod, store


def test_list_rubrics(seeded_db: Path, monkeypatch, capsys):
    real = rubric.list_rubrics
    monkeypatch.setattr(rubric, "list_rubrics", lambda db_path=None: real(db_path=seeded_db))
    monkeypatch.setattr(sys, "argv", ["run.py", "--list-rubrics"])
    rc = run_mod.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "h_rubric" in out
    assert "l_rubric" in out


def test_list_runs_empty(seeded_db: Path, monkeypatch, capsys):
    real = store.list_runs
    monkeypatch.setattr(
        store, "list_runs", lambda limit=20, db_path=None: real(limit=limit, db_path=seeded_db)
    )
    monkeypatch.setattr(sys, "argv", ["run.py", "--list-runs"])
    rc = run_mod.main()
    assert rc == 0
    assert "no evaluation runs" in capsys.readouterr().out


def test_missing_required_args_errors(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run.py"])
    with pytest.raises(SystemExit):
        run_mod.main()


def test_evaluate_writes_scores_json(seeded_db: Path, monkeypatch, tmp_path: Path, capsys):
    fake_result = {
        "rubric": "l_rubric",
        "score": 1.0,
        "max_score": 1.0,
        "all_pass": True,
        "n_criteria": 2,
        "n_passed": 2,
        "summary": "2/2 criteria passed. ALL PASS.",
        "criteria_results": [
            {"id": "c1", "title": "t", "verdict": "pass", "reasoning": "ok"}
        ],
        "judge_model": "fake-judge",
        "scored_at": "2026-01-01T00:00:00+00:00",
    }
    monkeypatch.setattr(
        "src.eval.scoring.evaluate_contract", lambda **kw: fake_result
    )
    real_store = store.store_result
    monkeypatch.setattr(
        store,
        "store_result",
        lambda result, contract_path=None, task_desc=None, db_path=None: real_store(
            result, contract_path=contract_path, task_desc=task_desc, db_path=seeded_db
        ),
    )

    contract = tmp_path / "contract.md"
    contract.write_text("合同正文", encoding="utf-8")
    out = tmp_path / "scores.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["run.py", "--contract", str(contract), "--rubric", "l_rubric", "--out", str(out)],
    )
    rc = run_mod.main()
    assert rc == 0
    assert out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["rubric"] == "l_rubric"
    assert data["all_pass"] is True
